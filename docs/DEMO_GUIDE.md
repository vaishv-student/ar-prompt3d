# Demo / recording guide

Once the server is confirmed working end-to-end, use this as the script
for the illustrative video and for the Experimental Results section.

## Before recording

1. `python3 server/app.py 8000` (first `/api/generate` call after a
   restart is slower — it loads the pipeline into memory).
2. Open <http://localhost:8000> in Chrome.
3. Have 3+ prompts ready, e.g.: "a small potted cactus", "a red toy
   race car", "a wooden treasure chest".

## Recording (QuickTime: File → New Screen Recording)

1. Show the start screen, click **Start (camera preview mode)**, grant
   camera access — show the live camera feed is real.
2. Type or **speak** a prompt (demonstrate voice input at least once),
   click **Generate**, let the progress bar run to completion. Note the
   time it takes — write it down for the report.
3. Tap to place the object in the scene. Show it appearing over the live
   camera feed.
4. Demonstrate interaction: click the object in the side list to select
   it, **drag** to move it, **scroll/pinch** to resize it.
5. Generate a second and third object with different prompts, place them
   both, show the object list managing multiple items.
6. Delete one with the ✕ button.
7. Briefly narrate (voiceover or on-screen text) the architecture: local
   Shap-E generation, no cloud API, WebXR path available on supported
   hardware (mention even if not demoed live).

## After recording

Fill in the report's Experimental Results section with:
- The 3+ prompts used and their measured generation latency.
- 2-3 still frames from the video (screenshots) as figures.
- Any failures/retries encountered.
- A one-line note on mesh quality at 32 inference steps.

Export the video as .mp4 (QuickTime exports .mov by default — re-export
or convert to .mp4 for the submission zip).
