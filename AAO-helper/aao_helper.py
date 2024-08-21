import asyncio

import discord
from discord import app_commands
from discord.ext import tasks
from typing import Optional
import re
import random
import types
import asyncio
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta

from params import *
from rank_grant import *
from embed_maker import *
from exhibition import *
from thread_auto_manage import *


@tree.command(description="Randomly assign sides for 2-5 players")
@app_commands.checks.bot_has_permissions(send_messages=True)
@app_commands.describe(
    player_one='Player one\'s name',
    player_two='Player two\'s name',
    player_three='Player three\'s name',
    player_four='Player four\'s name',
    player_five='Player five\'s name',
)
async def sides(interaction: discord.Interaction, player_one: str, player_two: str, player_three: Optional[str] = None,
                player_four: Optional[str] = None, player_five: Optional[str] = None):
    players = [player_one, player_two, player_three, player_four, player_five]
    players = [x for x in players if x]
    random.shuffle(players)
    amount = len(players)
    g = amount - 2
    game_sides = [
        ['<:axis:665257614002749482>', '<:allies:665257668797267989>'],
        ['<:allies:665257668797267989>', '<:germany_aa:660218154286448676>', '<:japan_aa:660218154638901279>'],
        ['<:us_r:1180308567694250055>', '<:united_kingdom:660218154378854401>', '<:germany_aa:660218154286448676>',
         '<:japan_aa:660218154638901279>'],
        ['<:soviet_union:660218154227859457>', '<:germany_aa:660218154286448676>',
         '<:united_kingdom:660218154378854401>', '<:japan_aa:660218154638901279>',
         '<:united_states:660218154160619533>'],
    ]
    await interaction.response.send_message('\n'.join(a + b for a, b in zip(game_sides[g], players)))


@tree.command(description="Moves showcase channel between cache and main category")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def toggle_showcase(interaction: discord.Interaction):
    showcase_dict = SHOWCASE_CHANNELS.get(interaction.channel_id)
    if not showcase_dict:
        await interaction.response.send_message("Must be in a showcase channel.", ephemeral=True)
        return
    else:
        showcase = interaction.guild.get_channel(interaction.channel_id)
        gallery = interaction.guild.get_channel(showcase_dict['gallery'])
        active = interaction.guild.get_channel(showcase_dict['active'])
        archive = interaction.guild.get_channel(ARCHIVE_CATEGORY)
        if not showcase or not active or not archive or not active.type == discord.ChannelType.category or not archive.type == discord.ChannelType.category:
            await interaction.response.send_message("Invalid data stored for showcase channel.", ephemeral=True)
            return
        if showcase.category == archive:
            if gallery:
                await gallery.edit(category=active)
            await showcase.edit(category=active)
            await interaction.response.send_message("Moved channel to active category!", ephemeral=True)
        else:
            if gallery:
                await gallery.edit(category=archive)
            await showcase.edit(category=archive)
            await interaction.response.send_message("Moved channel to archive category!", ephemeral=True)


# Helper function for refactoring
async def message_checks(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return

    if message.channel.id == 941854510647762954:  # server-logs
        return

    if "<@644511391302025226>" in message.content or "<@!644511391302025226>" in message.content:  # SpectacularVernacular -> SadPuppies
        await message.reply("Did you mean <@!948208421054865410>?")

    if re.search("aa1942calc.com/#/[a-zA-Z0-9-_]+", message.content.lower()):
        await message.edit(suppress=True)


last_msgs = {}


@bot.event
async def on_message(message: discord.Message):
    await message_checks(message)

    channel_id = message.channel.id

    ## anti-spam auto-ban
    prev = last_msgs.get(message.author.id)
    limit = 5
    if prev:
        if len(message.content) > 4 and message.content == prev[-1].content and all(
                channel_id != msg.channel.id for msg in prev):
            prev.append(message)
            if len(prev) >= limit:
                guild = message.author.guild
                bots_channel = guild.get_channel(SERVER_COMM_CH)
                if len(message.author.roles) <= 1:  # only Commanders role
                    await message.author.ban(reason=f"spammed {limit} times")
                    dm_message = f"You have been banned from the server {guild.name} for spamming in channels. This is to guard against link scams. However, if your message was not a scam, you should be unbanned shortly.\n\nIf you have recovered and secured your account, send a friend request to the Discord user '{guild.owner.name}' and you may be unbanned."
                    await message.author.send(dm_message)
                    await bots_channel.send(
                        f"Banned {message.author.mention} who joined <t:{round(message.author.joined_at.timestamp())}:f> for spamming {limit} times \nMessage: {'`' + message.clean_content() + '`'}\n\nSent to user in DMs: {dm_message}")
                else:
                    await bots_channel.send(
                        f"{guild.get_role(MOD_ROLE_ID).mention} {guild.get_role(STAFF_ROLE_ID).mention} Potential spam detected from member {message.author.mention} who has multiple roles")
        else:
            last_msgs[message.author.id] = [message]

    else:
        last_msgs[message.author.id] = [message]
    ##

    if message.content.startswith("/sync") and message.author.guild_permissions.manage_guild:
        bot.tree.copy_global_to(guild=message.guild)
        synced = await bot.tree.sync(guild=message.guild)
        await message.reply(f"Synced {len(synced)} app commands in guild {message.guild}")


@bot.event
async def on_message_edit(before, after):
    await message_checks(after)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await rank_reaction_add(payload)


@bot.event
async def on_member_join(member: discord.Member):
    await asyncio.sleep(60)
    await clean_member_roles(member)


# Don't know how to make this work, so just put it in on_message
@bot.command()
@commands.guild_only()
@commands.is_owner()
async def sync(ctx):
    ctx.bot.tree.copy_global_to(guild=ctx.guild)
    synced = await ctx.bot.tree.sync(guild=ctx.guild)
    await ctx.message.reply(f"Synced with {len(synced)} guilds")


@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")
    if not unarchiver.is_running():
        unarchiver.start()
    if not forum_closer.is_running():
        forum_closer.start()
    if not auto_update_season.is_running():
        auto_update_season.start()


# For persistent views
async def setup_hook_with_views(self):
    self.add_view(ExhibitionStartView())


bot.setup_hook = types.MethodType(setup_hook_with_views, bot)

# Start the bot
bot.run(TOKEN)
