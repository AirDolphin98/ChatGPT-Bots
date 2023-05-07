
import openai
import os
import sys
import importlib.util
from typing import Callable, Any
import sqlite3
import json
import discord
from discord.ext import commands
import asyncio
import tiktoken
from datetime import date
import timeit
import textwrap
import re
import copy
import backoff
import functools


if len(sys.argv) > 1:
    path_to_folder = sys.argv[1]
else:
    raise ValueError("No folder name argument provided")

with open('api_key.txt', 'r') as f:
    OPENAI_API_KEY = f.read().strip()
with open(os.path.join(path_to_folder,'token.txt'), 'r') as f:
    DISCORD_BOT_TOKEN = f.read().strip()

# Configure OpenAI API
openai.api_key = OPENAI_API_KEY

# Configure Discord bot
TOKEN = DISCORD_BOT_TOKEN
intents = discord.Intents.all()

database_path = os.path.join(path_to_folder,"dabs.db")
conn = sqlite3.connect(database_path)
cur = conn.cursor()

g_conn = sqlite3.connect("general.db")
g_cur = g_conn.cursor()

module_path = os.path.join(path_to_folder,"init.py")
sys.path.append(module_path)
spec = importlib.util.spec_from_file_location("init", module_path)
init = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init)


command_prefix = init.command_prefix
silence_prefix = init.silence_prefix
donate_link = init.donate_link
subscriber_rolename = getattr(init, 'subscriber_rolename', "AI Friend Supporter") # todo: can do this for every attr
g_cur.execute(
    """
    CREATE TABLE IF NOT EXISTS usage (
        folder_month TEXT PRIMARY KEY,
        token_usage INTEGER
    )
    """
)
def folder_month(): return path_to_folder+" : "+str(date.today().month) # better use number for month due to different localizations' month names
g_cur.execute("INSERT OR IGNORE INTO usage (folder_month, token_usage) VALUES (?, ?)", (folder_month(), 0))
g_conn.commit()
g_cur.execute("SELECT token_usage FROM usage WHERE folder_month=?", (folder_month(),))
token_usage = g_cur.fetchone()[0]

bot = commands.Bot(command_prefix=command_prefix, intents=intents, help_command=None)

# Channel IDs to monitor and chat in
auto_channels = init.auto_channels
reply_only_chs = init.reply_only_chs
channel_id_list = auto_channels + reply_only_chs
# IDs of Users whose messages the bot does not see
blocked_user_set = set()

discord_msg_char_limit = init.discord_msg_char_limit
chat_model = init.chat_model
ques_model = init.ques_model
pref_temp = init.pref_temp
pref_summ_temp = init.pref_summ_temp
token_limit = init.token_limit
convo_limit = init.convo_limit # in excess of preconvo
pref_max_resp_tokens = init.pref_max_resp_tokens
pref_summary_tokens = init.pref_summary_tokens

character_description: Callable[[Any, Any], str] = init.character_description
context_description: Callable[[Any, Any], str] = init.context_description

whether_respond = init.whether_respond

default_convos = init.default_convos


# Prompts always presented to the bot by default 
preconvo = [
    {'role':'system','content':character_description},
    {'role':'system','content':context_description},
]

preconvo_len = len(preconvo)

# the following is because 'bot' is invalid until bot.run
def preconvo_fill(bot, channel_id):
    precnv = copy.deepcopy(preconvo)
    channel = bot.get_channel(channel_id)
    for i in range(preconvo_len):
        precnv[i]['content'] = precnv[i]['content'](bot, channel)
    return precnv


convos = {channel_id: [] for channel_id in channel_id_list}
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS convos (
        channel_id INTEGER PRIMARY KEY,
        convo TEXT
    )
    """
)
conn.commit()
reply_queues = {channel_id: asyncio.Queue() for channel_id in channel_id_list}
reply_posts = {channel_id: [] for channel_id in channel_id_list}
unseen_msgs = {channel_id: set() for channel_id in channel_id_list}
responding = {channel_id: False for channel_id in channel_id_list}


### Main chatbot logic
def error_handle(func):
    @functools.wraps(func)
    async def wrapper(**kwargs):
        try:
            res = await func(**kwargs)
            return res
        except Exception as err:
            print("@error_handle decorator caught a blasted error:", err)
            raise
    return wrapper

@error_handle
@backoff.on_exception(backoff.expo, openai.error.RateLimitError, max_time=300)
async def backoff_Completion(**kwargs):
    global token_usage
    c = await openai.Completion.acreate(**kwargs)
    token_usage += c['usage']['total_tokens']
    return c # for acreate

@error_handle
@backoff.on_exception(backoff.expo, openai.error.RateLimitError, max_time=300)
async def backoff_ChatCompletion(**kwargs):
    global token_usage
    cc = await openai.ChatCompletion.acreate(**kwargs)
    token_usage += cc['usage']['total_tokens']
    return cc # for acreate

encoding = tiktoken.encoding_for_model(chat_model)

def token_len(text, enc=encoding):
    return len(enc.encode(text))

def total_token_len(cnv):
    return sum([token_len(m['content']) for m in cnv])

def free_space(cnv):
    # 10 is a magic constant representing a buffer for the role:, content:, etc. header labels and info in each message object
    # 20 is a magic constant representing buffer plus the header in formatted content which will attach to response
    return token_limit-total_token_len(cnv)-10*len(cnv)-pref_max_resp_tokens-20

# bug: summary starts with broken continuation of end of text, then “This text provides…”+summary
async def summarize(cont):
    summary_prompt = "Summarize the following text, and do NOT provide any continuation:\n\n"
    enc = tiktoken.encoding_for_model(ques_model)

    if token_len(cont,enc) > token_limit-token_len(summary_prompt,enc)-pref_summary_tokens: # safeguard for exceeding token_limit
        chunks = textwrap.wrap(cont, token_limit // 2, break_long_words=False)
        summary = ""
        prior_prompt = ""
        for chunk in chunks:
            if len(summary) > 0: prior_prompt = "[Summary of prior portion of the same text:]\n"
            summary += await backoff_Completion(
                model=ques_model,
                prompt=prior_prompt+summary+"\n\n"+summary_prompt+chunk,
                max_tokens=pref_summary_tokens,
                temperature=pref_summ_temp,
            )
            summary = summary.choices[0].text.strip()+" "
    else: 
        summary = await backoff_Completion(
            model=ques_model,
            prompt=summary_prompt+cont,
            max_tokens=pref_summary_tokens,
            temperature=pref_summ_temp,
        )
        summary = summary.choices[0].text.strip()

    return summary

# function to add new message to convo
async def add_to_convo(message, convo):
    is_self = isinstance(message, str)
    role = 'assistant' if is_self else 'user'
    formatted_content = bot.user.display_name+": "+message if is_self else message.author.display_name+": "+message.clean_content
    
    message_token_len = token_len(formatted_content)

    def no_free_space(): return message_token_len > free_space(convo)
    def long_content(i): return token_len(convo[i]['content']) > pref_summary_tokens * 2 # 2 is a magic constant for how big is summarize-worthy
    def history_len(): return len(convo)-preconvo_len

    if no_free_space():
        if message_token_len > token_limit // 2: # 2 is a magic constant, just a heuristic for when a message is too big
            formatted_content = await summarize(formatted_content)
        while no_free_space():
            i = preconvo_len
            init_hist_len = history_len()
            while no_free_space() and history_len() > init_hist_len // 2:
                # 2 is a magic constant for when to stop deleting and when to start summarizing. In theory, the outer while loop can repeat this halving like Zeno
                if long_content(i) or len(convo) == i:
                    break
                else:
                    convo.pop(i)
            while no_free_space() and i < len(convo):
                if long_content(i):
                    convo[i]['content'] = await summarize(convo[i]['content'])
                i += 1
    
    while len(convo) >= convo_limit + preconvo_len:
        popped = convo.pop(preconvo_len)
        print("\nPopped from convo: ", popped)
    
    added = {'role':role,'content':formatted_content}
    convo.append(added)
    print("\nAppended to convo: ", added, "\n")
    for line in convo:
            print(line['role'] + ": " + textwrap.wrap(line['content'], width=50)[0])
    print("\n")


# in auto channels, whether or not to respond to a message
async def should_respond(cnv):
    cnv_q = cnv.copy()
    cnv_q.append({'role':'system','content':whether_respond})
    chat_now = await backoff_ChatCompletion(
        model=chat_model,
        messages=cnv_q,
        max_tokens=1,
        temperature=pref_temp,
    )
    chat_now = chat_now.choices[0].message.content.strip()

    def y_or_n(expr):
        match = re.search(r'[YyNn]', expr)
        if match:
            ans = match.group()
            if ans == 'Y' or ans == 'y': 
                return True
            elif ans == 'N' or ans == 'n': 
                return False
        print("Match y_or_n failed")
        return True
    
    print("\nchat_now: ", chat_now, "\n")
    return y_or_n(chat_now)


async def respond(msg, cnv):
    cont = await backoff_ChatCompletion(
        model=chat_model,
        messages=cnv,
        max_tokens=pref_max_resp_tokens,
        temperature=pref_temp,
    )
    unfin = cont.choices[0].finish_reason == 'length'
    print(f"\nfinish_reason: '{cont.choices[0].finish_reason}'")
    cont = cont.choices[0].message.content.strip()
    print("\nResponse: ", cont, "\n\n")

    def name_strip(text):
        chopped = text.split(": ")
        while len(chopped) > 1 and chopped[0] in (bot.user.display_name, bot.user.name):
            chopped.pop(0)
        return ": ".join(chopped)
    
    def sub_mentions(msg, text):
        for mem in [msg.author] + msg.mentions:
            m_pattern = rf"@{re.escape(mem.display_name)}"
            text = re.sub(m_pattern, mem.mention, text)
        for channel in [msg.channel] + msg.channel_mentions:
            c_pattern = rf"#{re.escape(channel.name)}"
            text = re.sub(c_pattern, channel.mention, text)
        return text
    
    cont = name_strip(cont)

    while len(cont) > discord_msg_char_limit:
        cont = await summarize(cont)
    
    cont = sub_mentions(msg, cont)

    return cont, unfin


def is_to_bot(msg):
    if (msg.reference and 
    msg.reference.resolved and 
    msg.reference.resolved.author == bot.user):
        return True
    for mem in msg.mentions:
        if mem == bot.user:
            return True
    return False

# Allow continuation of response when it is cut short
async def respond_list(msg, cnv):
    cnv_q = cnv.copy()
    continue_cmd = {'role':'system','content':"Continue"}
    cont_list = []
    unfinished = True
    i = 1
    while unfinished:
        ith = " #"+str(i) if i > 1 else ""
        print(f"Starting respond{ith} in channel #{msg.channel.name}")
        t_bef = timeit.default_timer()
        async with msg.channel.typing():
            cont, unfinished = await respond(msg, cnv_q)
        t_aft = timeit.default_timer()
        print(f"End of respond{ith} in channel #{msg.channel.name}: {t_aft - t_bef} sec")
        cont_list.append(cont)

        if unfinished:
            await add_to_convo(cont, cnv_q)
            cnv_q.append(continue_cmd)
            i += 1

    return cont_list


async def chat(msg, c_id):
    async def respond_recurse(msg_channel):
        print(f"Starting recursed should_respond in #{msg.channel.name}")
        t_bef = timeit.default_timer()
        chat_now = await should_respond(convos[c_id])
        t_aft = timeit.default_timer()
        print(f"End of recursed should_respond in #{msg.channel.name}: {t_aft - t_bef} sec")


    async def reply_wrap():
        reply_queue = reply_queues[c_id]
        unseen_msgs[c_id].clear()
        convo = await reply_queue.get()
        for r in reply_posts[c_id]: 
            await add_to_convo(r, convo)

        cont_list = await respond_list(msg, convo)

        for cont in cont_list:
            await add_to_convo(cont, convos[c_id])
            await add_to_convo(cont, reply_posts[c_id])
            await msg.reply(cont)

        reply_queue.task_done()
        if reply_queue.empty():
            reply_posts[c_id] = []
            # recurse the normal respond route
            if unseen_msgs[c_id]:
                await respond_wrap()

    async def respond_wrap():
        if responding[c_id] or not reply_queues[c_id].empty(): 
            return
        print(f"Starting should_respond in channel #{msg.channel.name}")
        t_bef = timeit.default_timer()
        chat_now = await should_respond(convos[c_id])
        t_aft = timeit.default_timer()
        print(f"End of should_respond in channel #{msg.channel.name}: {t_aft - t_bef} sec")

        if msg in unseen_msgs[c_id]:
            if chat_now:
                responding[c_id] = True
                unseen_msgs[c_id].clear()

                # needs should_resp and clear unseen
                cont_list = await respond_list(msg, convos[c_id])

                for cont in cont_list:
                    await add_to_convo(cont, convos[c_id])
                    await msg.channel.send(cont)
                
                # problem is that in recurse, we don't have a particular msg

                # RECURSE if unseen nonempty
                # recurse regardless of whether resping is from reply or resp
                # make sure reply too, but redundant from reply cmd don't intercede
                # i.e. if already responding, do not start a recurse resp
                # but to be clear, do not nullify the new-started "responding" of another 

                responding[c_id] = False # what if someone else is responding too?
            else:
                unseen_msgs[c_id].remove(msg)
        else:
            print(f"Skipped a message in #{msg.channel.name}")        
    
    if is_to_bot(msg):
        await reply_queues[c_id].put(convos[c_id].copy())
        await reply_wrap()
    else:
        await respond_wrap()


### Events and commands

@bot.event
async def on_message(message):
    channel_id = message.channel.id
    if channel_id not in channel_id_list:
        return
    
    if message.author.bot or message.author.system: #if want to allow other bots, exclude self, since self messages added to convo internally
        return
    
    if (message.author.id, message.guild.id) in blocked_user_set or message.content.startswith(silence_prefix):
        return
    
    # If the message is a command, execute it 
    await bot.process_commands(message)

    ctx = await bot.get_context(message)
    if ctx.valid: # If the message is a command, stop here
        return

    if channel_id in reply_only_chs and not is_to_bot(message):
        return

    try:
        await add_to_convo(message, convos[channel_id])
        unseen_msgs[channel_id].add(message)
        await chat(message, channel_id)

        serialized_convo = json.dumps(convos[channel_id])
        cur.execute(
            "INSERT OR REPLACE INTO convos (channel_id, convo) VALUES (?, ?)",
            (channel_id, serialized_convo)
        )
        conn.commit()
        g_cur.execute(
            "INSERT OR REPLACE INTO usage (folder_month, token_usage) VALUES (?, ?)", 
            (folder_month(), token_usage)
        )
        g_conn.commit()

    except:
        await message.channel.send(":anger: Experiencing technical difficulties, please try again later :thumbsup:")
        raise


@bot.hybrid_command(description="Lists commands")
async def help(ctx):
    page = f"**Commands __{bot.user.display_name}__ can run:**\n"
    page += f"Bot will ignore messages that start with: {silence_prefix}\n"
    unsorted = []
    cog_sorted = { cg: [] for cg in bot.cogs }
    page += f"\n__Prefix for all following commands:__ {bot.command_prefix}\n"
    for cm in bot.commands:
        if cm.hidden: continue
        c = f"{cm.name}: {cm.description}\n"
        for a in cm.aliases:
            c += "- {a}\n"
        if cm.cog_name:
            cog_sorted[cm.cog_name] = c
        else:
            unsorted.append(c)
    for uc in unsorted:
        page += uc
    for cg, cl in cog_sorted.items():
        page += "__Category: "+cg+"__\n"
        for cc in cl:
            page += cc
    await ctx.send(page)


@bot.hybrid_command(description="Link to support the developer")
async def donate(ctx):
    await ctx.send(f"Donate: {donate_link}")


@bot.hybrid_command(description="Resets the conversation history in the channel")
async def reset_convo(ctx):
    c_id = ctx.channel.id
    convos[c_id] = preconvo_fill(bot, c_id) + default_convos.get(c_id, [])
    serialized_convo = json.dumps(convos[c_id])
    cur.execute(
        "INSERT OR REPLACE INTO convos (channel_id, convo) VALUES (?, ?)",
        (c_id, serialized_convo)
    )
    conn.commit()
    await ctx.send("Memory of this channel's conversation has been reset!")


@bot.hybrid_command(description="Makes the bot post a message that it considers its own")
@commands.has_role(subscriber_rolename)
async def spoof(ctx, message):
    await ctx.send(message)
    await add_to_convo(message, convos[ctx.channel.id])


@bot.command(hidden=True)
@commands.is_owner() # AirDolphin98
async def sync_global(ctx):
    synced = await bot.tree.sync()
    await ctx.send(f"Synced the following commands across all servers: {synced}")


@bot.command(hidden=True)
@commands.is_owner() # AirDolphin98
async def db_dump(ctx):
    cur.execute("SELECT channel_id, convo FROM convos")
    dump = ""
    for r in cur.fetchall():
        dump += "\n\n" + str(r[0]) + ": " + r[1] + "\n"
    for m in textwrap.wrap(dump, width=discord_msg_char_limit-10):
        await ctx.send("```"+m+"```")


@bot.command(hidden=True)
@commands.is_owner() # AirDolphin98
async def usage_dump(ctx):
    g_cur.execute("SELECT * FROM usage")
    tab = ["(folder : month, tokens)"] + [str(r) for r in g_cur.fetchall()]
    if not ctx.author.dm_channel: await ctx.author.create_dm()
    await ctx.author.dm_channel.send("\n".join(tab))


@bot.event
async def on_ready():
    cur.execute("SELECT channel_id, convo FROM convos")
    refresh = dict(cur.fetchall())
    for c_id in channel_id_list:
        convos[c_id] = json.loads(refresh[c_id]) if c_id in refresh else preconvo_fill(bot, c_id) + default_convos.get(c_id, [])

    print(f"{bot.user.name} has connected to Discord!")


# Start the bot
bot.run(TOKEN)
