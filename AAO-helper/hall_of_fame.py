import discord

from params import *
from discord import app_commands
from embed_maker import CreateEmbedModal
from rank_grant import *
import re
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta


HOF_ROLE_ID = 1008640154128367627
HOF_CH = 1008636617956790332  #hall-of-fame
HOF_TIME_FORMAT = "%b %d, %Y"

TOURNAMENT_TYPES = [app_commands.Choice(name='Solos', value='Solos'), app_commands.Choice(name='Duos', value='Duos'), app_commands.Choice(name='Blitz', value='Blitz')]
CHAMP_ROLE_ID = 724102613884207195

SUPR_CMDR_ROLE_ID = 947651702302081094
GEN_ROLE_ID = 945565758245707808

"""Debugging in A&AO Test Server"""
if DEBUG:
    HOF_ROLE_ID = 1278026855630241822
    HOF_CH = 864688826005454899  #general
    CHAMP_ROLE_ID = 1278026981077942272
    SUPR_CMDR_ROLE_ID = 1278158991582560358
    GEN_ROLE_ID = 1278159222500233308
""""""

hof_group = discord.app_commands.Group(name="hall_of_fame", description="Commands for posting Hall of Fame embeds and awarding roles")
tree.add_command(hof_group)


@hof_group.command(description="Posts Top 10 embed in Hall of Fame channel")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(send_messages=True, manage_roles=True)
@app_commands.describe(
    rank_1_axis='@mention or user ID of #1 Axis player (put "n/a" if none)',
    rank_1_allies='@mention or user ID of #1 Allies player (put "n/a" if none)',
    top_10s='@mentions or user IDs of non-#1 Top 10 Platinum players for the season (put "n/a" if none)',
    img_url='URL of screenshot of final leaderboard (tip: can post image on Discord and copy link)',
    season_num='Season number if not current season'
)
async def top_10(interaction: discord.Interaction, rank_1_axis: str, rank_1_allies: str, top_10s: str, img_url: str, season_num: int = None):
    if interaction.channel_id != HOF_CH:
        await interaction.response.send_message("Must be in Hall of Fame channel", ephemeral=True)
        return
    r1ax = re.findall(r"(\d+)", rank_1_axis)
    r1al = re.findall(r"(\d+)", rank_1_allies)
    tops = re.findall(r"(\d+)", top_10s)
    if len(r1ax) > 1 or len(r1al) > 1:
        await interaction.response.send_message("Error: provided more than one @mention or ID per #1 Rank)",
                                                ephemeral=True)
        return

    end_ts = None
    cur.execute(
        "SELECT season_num, end_timestamp FROM current_season_end WHERE guild_id = ?",
        (interaction.guild_id,)
    )
    current_end = cur.fetchone()
    if not current_end:
        season_num = "__"
        end_ts = datetime.now(timezone.utc).timestamp()
    elif not season_num:
        season_num, end_ts = current_end
    hof_list = []
    time_added = datetime.now(timezone.utc).timestamp()
    row_list = []
    description = ""
    if r1ax:
        user = interaction.guild.get_member(int(r1ax[0]))
        if user:
            description += f"#1 Axis {user.mention} {user.display_name}\n"
            hof_list.append(user)
        if current_end:
            row_list.append((time_added, user.id, RANK_ID_DICT[RANK1_LIST[0]], season_num, ""))
            row_list.append((time_added, user.id, RANK_ID_DICT[RANK_LIST[0]], season_num, ""))
    if r1al:
        user = interaction.guild.get_member(int(r1al[0]))
        if user:
            description += f"#1 Allies {user.mention} {user.display_name}\n"
            hof_list.append(user)
        if current_end:
            row_list.append((time_added, user.id, RANK_ID_DICT[RANK1_LIST[1]], season_num, ""))
            row_list.append((time_added, user.id, RANK_ID_DICT[RANK_LIST[0]], season_num, ""))
    for u_id in tops:
        user = interaction.guild.get_member(int(u_id))
        if user:
            description += f"{user.mention} {user.display_name}\n"
            hof_list.append(user)
        if current_end:
            row_list.append((time_added, user.id, RANK_ID_DICT[RANK_LIST[0]], season_num, ""))

    title = f"Ranked Season {season_num} - Top 10 Platinum"
    footer = None
    if end_ts:
        footer = datetime.strftime(datetime.fromtimestamp(end_ts, timezone.utc), HOF_TIME_FORMAT)
    color = None
    image = img_url

    class Top10EmbedModal(CreateEmbedModal):
        async def on_submit(self, interaction: discord.Interaction):
            hof_role = interaction.guild.get_role(HOF_ROLE_ID)
            await super().on_submit(interaction)
            if current_end:
                current_season_num, end_timestamp = current_end
                await add_records(interaction, row_list, current_season_num, end_timestamp)
            for usr in hof_list:
                await usr.add_roles(hof_role)
    await interaction.response.send_modal(Top10EmbedModal(vals=(title, description, footer, color, image)))


@hof_group.command(description="Posts tournament final results embed in Hall of Fame channel")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(send_messages=True, manage_roles=True)
@app_commands.describe(
    kind='The type of tournament',
    number='The ordinal number iteration of this type of tournament. Displayed in title as written',
    champions='@mention(s) or user ID(s) of winner(s). NB: does not check for correct count',
    finalists='@mention(s) or user ID(s) of runner(s)-up. NB: does not check for correct count',
    date='The date of the result (UTC). Will simply be displayed in footer as written'
)
@app_commands.choices(kind=TOURNAMENT_TYPES)
async def tournament(interaction: discord.Interaction, kind: app_commands.Choice[str], number: str, champions: str, finalists: str, date: Optional[str] = None):
    if interaction.channel_id != HOF_CH:
        await interaction.response.send_message("Must be in Hall of Fame channel", ephemeral=True)
        return
    champs = re.findall(r"(\d+)", champions)
    runners_up = re.findall(r"(\d+)", finalists)
    title = f"{kind.value} Tournament {number} Champion{'s' if len(champs) != 1 else ''}"
    hof_list = []
    champs_list = []
    description = ""
    if not date:
        date = datetime.strftime(datetime.fromtimestamp(datetime.now(timezone.utc).timestamp(), timezone.utc), HOF_TIME_FORMAT)
    for c_id in champs:
        user = interaction.guild.get_member(int(c_id))
        if user:
            description += f":trophy: {user.display_name} {user.mention}\n"
            hof_list.append(user)
            champs_list.append(user)
    description += f"\n__*Finalist{'s' if len(runners_up) != 1 else ''}:*__\n"
    for r_id in runners_up:
        user = interaction.guild.get_member(int(r_id))
        if user:
            description += f"{user.display_name} {user.mention}\n"
            hof_list.append(user)

    class TournamentEmbedModal(CreateEmbedModal):
        async def on_submit(self, interaction: discord.Interaction):
            hof_role = interaction.guild.get_role(HOF_ROLE_ID)
            champ_role = interaction.guild.get_role(CHAMP_ROLE_ID)
            await super().on_submit(interaction)
            for usr in champs_list:
                await usr.add_roles(champ_role)
            for usr in hof_list:
                await usr.add_roles(hof_role)
            await interaction.followup.send(
                "Remember to manually give specific Champion role to champion(s).\n\nAlso, if the policy is to dethrone the previous champion, remember to remove specific Champion role from previous winner(s) AND Champions role if not champion of anything else.",
                ephemeral=True)

    await interaction.response.send_modal(TournamentEmbedModal(vals=(title, description, date, None, None)))


@hof_group.command(description="Posts league current season's Generals embed in Hall of Fame channel")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(send_messages=True, manage_roles=True)
@app_commands.describe(
    number='The number of the current, newly started League season. Displayed in title as written',
    generals='@mentions or user IDs of Generals. First listed is Supreme Commander',
    date_range='The date range of the season (UTC). Write "TBD" if season is ongoing'
)
@app_commands.choices(update_roles=[app_commands.Choice(name="Yes, give this group the Generals and Supreme Commander roles", value=1), app_commands.Choice(name="No, this is not for the current season, so leave roles alone", value=0)])
async def league(interaction: discord.Interaction, number: str, generals: str, date_range: str, update_roles: app_commands.Choice[int]):
    if interaction.channel_id != HOF_CH:
        await interaction.response.send_message("Must be in Hall of Fame channel", ephemeral=True)
        return
    gens = re.findall(r"(\d+)", generals)
    title = f"League Season {number} Generals"
    gens_list = []
    description = ""
    start = True
    for g_id in gens:
        user = interaction.guild.get_member(int(g_id))
        if user:
            if start:
                description += f":white_flower: {user.display_name} {user.mention} *Supreme Commander*\n"
            else:
                description += f"{user.display_name} {user.mention}\n"
            start = False
            gens_list.append(user)

    if update_roles.value:
        class LeagueEmbedModal(CreateEmbedModal):
            async def on_submit(self, interaction: discord.Interaction):
                hof_role = interaction.guild.get_role(HOF_ROLE_ID)
                s_c_role = interaction.guild.get_role(SUPR_CMDR_ROLE_ID)
                gen_role = interaction.guild.get_role(GEN_ROLE_ID)
                await super().on_submit(interaction)
                for usr in s_c_role.members:
                    await usr.remove_roles(s_c_role)
                await gens_list[0].add_roles(s_c_role)
                for usr in gens_list:
                    await usr.add_roles(hof_role, gen_role)
                for usr in gen_role.members:
                    if usr not in gens_list:
                        await usr.remove_roles(gen_role)
                await interaction.followup.send("Remember to edit the previous season's embed footer from TBD.",
                                                   ephemeral=True)
        await interaction.response.send_modal(LeagueEmbedModal(vals=(title, description, date_range, None, None)))
    else:
        await interaction.response.send_modal(CreateEmbedModal(vals=(title, description, date_range, None, None)))

