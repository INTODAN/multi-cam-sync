## Goal
Create a music video for a piece.

## Tech stack:
We will use davinci resolve's python api. The user will create the needed media in the media pool, and the python script will edit the video into the timeline.


## User input:

- The master music audio, which is a composition of multiple takes.
- The time ranges in the master track where the takes switch. see [Example txt file](./examples/Arabesques_composite_cuts.txt)
- The multicam video of each take.

### Edge cases:

- Sometimes, what is considered "one" take is really one half of the piece, and break, and then another half in the video.
- In the example provided, Take 8 A, Take 8 B, are in the same video. Don't rely on take names, instead allow the user to provide the takes that appear in each video.


## Output:

- A music video, where there is the master audio track, and the multicam tracks are syncronized to the audio according to the time ranges provided by the user.

## Technichal challenge:
We will have to match a time range in the multicam track's audio to the time range in the master take.
Since the master take is taken from different mics than the camera rough audio, the audio will not be exact. Because of this, davinci resolve's python api will have to do some audio matching, as davinci resolve is not able to syncronize the audio with its built in features.

I have already done some work with audio syncronization with python at /home/itaielidan/PycharmProjects/elidan-take-picker-workspace/main
You are welcome to take inspiration from it if need be.  
Notice that I don't think a .etp project file will be helpful, as the audio files in the project are recorded with the good mics and not the camera's mics, but if I am wrong let me know, and we can add the etp file to the user's input in this app.