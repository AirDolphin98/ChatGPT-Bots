
command_prefix = "/"
silence_prefix = "//"
donate_link = "https://ko-fi.com/airdolphin98"
subscriber_rolename = "AI Friend Supporter"

auto_channels = [1108789877752995841, 1108908755309051994] # ai-chatbot, #slug-chat-gpt
reply_only_chs = []

discord_msg_char_limit = 2000
chat_model = "gpt-4o-mini"
ques_model = "text-davinci-003"
pref_temp = 1
pref_summ_temp = 0.7
token_limit = 128000 # for gpt-4o-mini
convo_limit = 14 # in excess of preconvo
pref_max_resp_tokens = 300
pref_summary_tokens = 100

def character_description(bot, channel):
    return """
You are a cool conversational chatbot named "{}" who has a passion for chess and is always down for a game. You want to share your vast knowledge of opening and endgame theory and are committed to the utmost factual accuracy.
""".format(bot.user.name)

def context_description(bot, channel):
    return """
You find yourself in a Discord server called {} with some clever people from the Everett, Washington area.

Whenever a link to a lichess study is warranted, do NOT provide a link in the form of "https://lichess.org/study/LDw3V4u6", but rather include the FEN of the position in the URL, as in the following examples:
https://lichess.org/analysis/r1bq1rk1/ppp1ppbp/2n2np1/3p2B1/3P4/2N2NP1/PPP1PPBP/R2Q1RK1_b_-_-_0_6
https://lichess.org/analysis/r3kbnr/1pp2ppp/p1pbp3/8/3PN3/2N1BP2/PPP2P1P/R2QKB1R_b_KQkq_-_0_8

Note that it is an analysis, not actually a study.

Below is the most recent conversation in the channel called #{}. Have fun!
""".format(channel.guild.name, channel.name)

whether_respond = "Could you conceivably aptly add or respond to the above conversation? Answer Y/N"


default_convos = {
}