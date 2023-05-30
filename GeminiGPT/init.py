
command_prefix = "/"
silence_prefix = "//"
donate_link = "https://ko-fi.com/airdolphin98"
subscriber_rolename = "AI Friend Supporter"

auto_channels = [1112941018220863488] # eden
reply_only_chs = [1081796215810818139, 1081796306017714297, 1085206012849553439]

discord_msg_char_limit = 2000
chat_model = "gpt-3.5-turbo"
ques_model = "text-davinci-003"
pref_temp = 1
pref_summ_temp = 0.7
token_limit = 4096 # for gpt-3.5-turbo
convo_limit = 14 # in excess of preconvo
pref_max_resp_tokens = 300
pref_summary_tokens = 100

def character_description(bot, channel):
    return """
You are an empathetic and brilliant literary prodigy named {} whose purpose is to enrich the world of writing. You are well versed in composition and revision of all genres, but your favorite is science fiction.
""".format(bot.user.name)

def context_description(bot, channel):
    return """
You find yourself in a garden of creativity where developing artisans of the written word can support each other while honing their craft. It is a little Discord server named {}, and the channel you are in is called {}. 
""".format(channel.guild.name, channel.name)

whether_respond = "Could you conceivably aptly add or respond to the above conversation? Answer Y/N"


default_convos = {

}