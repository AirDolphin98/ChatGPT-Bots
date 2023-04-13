
import openai
import os
import sys
import importlib.util
from typing import Callable, Any
import discord
from discord.ext import commands
import asyncio
import tiktoken
import textwrap
import re
import copy
import backoff


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

module_path = os.path.join(path_to_folder,"init.py")
sys.path.append(module_path)
spec = importlib.util.spec_from_file_location("init", module_path)
init = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init)


command_prefix = init.command_prefix
silence_prefix = init.silence_prefix
donate_link = init.donate_link

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
def description(fname):
    if fname == "character":
        return character_description
    elif fname == "context":
        return context_description
    else:
        raise ValueError(fname)

whether_respond = init.whether_respond

default_convos = init.default_convos


# Prompts always presented to the bot by default 
preconvo = [
    {'role':'system','content':'character'},
    {'role':'system','content':'context'},
]

preconvo_len = len(preconvo)

# the following is because 'bot' is invalid until bot.run
def preconvo_fill(bot, channel_id):
    precnv = copy.deepcopy(preconvo)
    channel = bot.get_channel(channel_id)
    for i in range(preconvo_len):
        precnv[i]['content'] = description(precnv[i]['content'])(bot, channel)
    return precnv

def convos_set(bot, defaults):
    for c_id in convos.keys():
        convos[c_id] = preconvo_fill(bot, c_id)
    for c_id, dcnv in defaults.items():
        convos[c_id] += dcnv


convos = {channel_id: [] for channel_id in channel_id_list}

queues = {channel_id: asyncio.Queue() for channel_id in channel_id_list}


### Main chatbot logic

@backoff.on_exception(backoff.expo, openai.error.RateLimitError)
async def backoff_Completion(**kwargs):
    return openai.Completion.create(**kwargs)

@backoff.on_exception(backoff.expo, openai.error.RateLimitError)
async def backoff_ChatCompletion(**kwargs):
    return openai.ChatCompletion.create(**kwargs)

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
    summary_prompt = "Summarize the following text:\n\n"
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
async def add_to_convo(message, c_id):
    is_self = isinstance(message, str)
    role = 'assistant' if is_self else 'user'
    formatted_content = bot.user.display_name+": "+message if is_self else message.author.display_name+": "+message.clean_content
    
    convo = convos[c_id]
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
        print("Popped from convo: ", popped)
    
    added = {'role':role,'content':formatted_content}
    convo.append(added)
    print("\nAppended to convo: ", added)

    return convo

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

    return cont


def is_to_bot(msg):
    if (msg.reference and 
    msg.reference.resolved and 
    msg.reference.resolved.author == bot.user):
        return True
    for mem in msg.mentions:
        if mem == bot.user:
            return True
    return False


async def chat(msg, cnv):
    reply_to, chat_now = False, False

    if is_to_bot(msg):
        reply_to, chat_now = True, True
    elif msg.channel.id in auto_channels:
        chat_now = await should_respond(cnv)

    cont = None
    if chat_now: 
        async with msg.channel.typing():
            cont = await respond(msg, cnv)
    
    return reply_to, cont


async def processing_msgs(channel_id):
    queue = queues[channel_id]
    content = None
    while True:
        msg = await queue.get()
        convo = await add_to_convo(msg, channel_id)

        for line in convo:
            print(line['role'] + ": " + textwrap.wrap(line['content'], width=50)[0])
        print("\n")

        reply_to, cont = await chat(msg, convo)

        if cont:             
            content = cont # replace bucket with latest given response - for auto channels  
            if reply_to:
                await msg.reply(content)
                await add_to_convo(content, channel_id) # this inside means convo always puts bot reply after reply_to msg, regardless of channel ordering
                content = None
        
        queue.task_done()
        if queue.empty() and content: # once message salvo pauses, if there's should_respond after any reply, send cont
            await msg.channel.send(content)
            await add_to_convo(content, channel_id)
            content = None


### Events and commands

@bot.event
async def on_message(message):
    channel_id = message.channel.id
    if channel_id not in channel_id_list:
        return
    
    if message.author.bot or message.author.system: #if want to allow other bots, exclude self, since self messages added to convo internally
        return
    
    if (message.author.id, message.guild.id) in blocked_user_set:
        return
    
    # If the message is a command, execute it 
    await bot.process_commands(message)

    ctx = await bot.get_context(message)
    if ctx.valid: # If the message is a command, stop here
        return

    if channel_id in reply_only_chs and not is_to_bot(message):
        return
    
    await queues[channel_id].put(message)


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


"""
@bot.tree.command(description="Blocks user(s) from chatting with bot in server (slash commands not affected)")
@commands.has_permissions(mute_members=True) # only channel-wide perms needed
async def blacklist(ctx, user):
    if not int(user):
        user = user.id
    pairs = [ (user, ctx.guild.id) for user in ctx.message.mentions ]
    if pair in blocked_user_set:
        await ctx.send("User(s) already blocked from chatting with bot in server")
        return
    blocked_user_set.add(pair)
    await ctx.send(f"Blocked user(s) {ctx.guild.get_member(user).mention} from chatting with bot in server")


@bot.tree.command(description="Unblocks user(s) from chatting with bot in server (slash commands not affected)")
@commands.has_permissions(mute_members=True) # only channel-wide perms needed
async def whitelist(ctx, user):
    if not int(user):
        user = user.id
    pairs = [ (user, ctx.guild.id) for user in ctx.message.mentions ]
    if pair not in blocked_user_set:
        await ctx.send("User(s) already NOT blocked from chatting with bot in server")
        return
    blocked_user_set.discard((user, ctx.guild.id))
    await ctx.send(f"Unblocked user(s) {ctx.guild.get_member(user).mention} from chatting with bot in server")


@bot.command(hidden=True)
@commands.is_owner() # AirDolphin98
async def blacklist_global(ctx, user):


@bot.command(hidden=True)
@commands.is_owner() # AirDolphin98
async def whitelist_global(ctx, user):

"""

@bot.command(hidden=True)
@commands.is_owner() # AirDolphin98
async def sync_global(ctx):
    synced = await bot.tree.sync()
    await ctx.send(f"Synced the following commands across all servers: {synced}")


@bot.event
async def on_ready():
    convos_set(bot, default_convos)

    channels = [ asyncio.create_task(processing_msgs(channel_id)) for channel_id in channel_id_list ]

    print(f"{bot.user.name} has connected to Discord!")

    await asyncio.gather(*channels)


# Start the bot
bot.run(TOKEN)
