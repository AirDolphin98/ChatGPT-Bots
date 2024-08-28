import discord
from discord.ext import commands
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
intents = discord.Intents.all()

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)
tree = bot.tree

conn = sqlite3.connect("info.db")
cur = conn.cursor()

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS threads_persist (
        channelthread_id INTEGER PRIMARY KEY
    )
    """
)
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS forum_posts_close (
        forum_id INTEGER PRIMARY KEY,
        days_wait REAL,
        lock INTEGER
    )
    """
)
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS ranks_added (
        time_added REAL PRIMARY KEY,
        user_id INTEGER,
        rank TEXT,
        season_num INTEGER,
        note TEXT
    )
    """
)
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS current_season_end (
        guild_id INTEGER PRIMARY KEY,
        season_num INTEGER,
        end_timestamp REAL
    )
    """
)
cur.execute(  # currently channel is expected to take a json serialized list of exhibition channel labels
    """
    CREATE TABLE IF NOT EXISTS exhibition_users (
        user_id INTEGER PRIMARY KEY,
        channel TEXT
    )
    """
)
conn.commit()

txt_views_dir = "txt_views"
if not os.path.exists(txt_views_dir):
    os.makedirs(txt_views_dir)
show_ranks_path = os.path.join(txt_views_dir, "show_ranks.txt")
with open(show_ranks_path, 'w') as f:
    pass
deleted_ranks_path = os.path.join(txt_views_dir, "deleted_ranks.txt")
with open(deleted_ranks_path, 'w') as f:
    pass
illformed_ranks_path = os.path.join(txt_views_dir, "illformed_ranks.txt")
with open(illformed_ranks_path, 'w') as f:
    pass
upload_ranks_path = os.path.join(txt_views_dir, "upload_ranks.txt")
with open(upload_ranks_path, 'w') as f:
    pass

DEBUG = False

STAFF_ROLE_ID = 943827276104097842
MOD_ROLE_ID = 659883868635267075
BEAMDOG_ROLE_ID = 610480003230072833
SERVER_COMM_CH = 670090977356021780 #server-logs

TITLE_LIMIT = 256
DESC_LIMIT = 4096
FOOTER_LIMIT = 2048

ARCHIVE_CATEGORY = 939908442083176459 #CACHE
TOURNAMENTS_CATEGORY = 731709452213944371 #TOURNAMENTS
SHOWCASE_CHANNELS = {
    948991011223379968: { #league-showcase
        'gallery': 948992296458784788, #grandstands
        'active': 776900323032956929 #A&A LEAGUE
    },
    731709533805608961: { #solos-showcase-1
        'gallery': 949939893449134111, #peanut-gallery-1
        'active': TOURNAMENTS_CATEGORY
    },
    946212630459220028: { #solos-showcase-2
        'gallery': 946226164597399652, #peanut-gallery-2
        'active': TOURNAMENTS_CATEGORY
    },
    949006458031337563: { #duos-showcase-1
        'gallery': 949939233404125185, #duos-peanut-gallery-1
        'active': TOURNAMENTS_CATEGORY
    },
    949006487466942545: { #duos-showcase-2
        'gallery': 949939291088371782, #duos-peanut-gallery-2
        'active': TOURNAMENTS_CATEGORY
    },
    944192041133416488: { #blitz-showcase
        'gallery': 1170113724359659650, #blitz-peanut-gallery
        'active': TOURNAMENTS_CATEGORY
    },
    724102588571582554: { #solos-finals
        'gallery': None,
        'active': TOURNAMENTS_CATEGORY
    },
    916778542023471144: { #ll-solos-finals
        'gallery': None,
        'active': TOURNAMENTS_CATEGORY
    },
    901995070784438274: { #duos-finals
        'gallery': None,
        'active': TOURNAMENTS_CATEGORY
    }
}

"""Debugging in A&AO Test Server"""
if DEBUG:
    STAFF_ROLE_ID = 1265197758449713233
    MOD_ROLE_ID = 864690035915358258
    SERVER_COMM_CH = 1265198095860502671

    ARCHIVE_CATEGORY = 975899857959141416
    SHOWCASE_CHANNELS = {
        940445952534257695: {
            'gallery': 941087323054030878,
            'active': 864688826005454898
        }
    }
""""""
