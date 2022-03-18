
# number of subject profiles to create
# (more may be created if necessary to have an equal number
# for each condition)
n_profiles = 150

# 20 minutes to complete the main section
timeout_secs = 60*20

audio_dir = 'audio'

qnaire_quests = [
    ['radio', 'What is your age range?',
     '18-24', '25-34', '35-44',
     '45-54', '55-64', '65 and older'],
    ['radio', 'What is your highest completed level of education?',
     'Less than high school diploma',
     'High school diploma or equivalent (for example: GED)',
     'Some college credit, no degree',
     'Trade/technical/vocational training',
     'Associate degree',
     'Bachelor’s degree',
     'Master’s degree',
     'Professional degree',
     'Doctorate degree'],
    ['shorttext', 'What is your native language?'],
    ['shorttext', 'List any other languages you speak'
     ' (to any level of ability);'
     ' answer "none" if no other languages'],
    ['shorttext', 'Briefly describe any prior experience with'
     ' or knowledge of linguistics you have'],
#    ['radio', 'Do you have any significant hearing problems'
#     ' that would make it difficult for you to take part'
#     ' in an experiment involving listening?', 'Yes', 'No']
]

exit_qnaire_quests = [
    ['text', 'Please describe the process you used when making judgments'
     ' about the nonsense words in as much detail as possible.']
]
