You are an object grounding expert checking someone else's detections in a repair video.

Context: <<CONTEXT>>

Each image shows one numbered candidate that was detected as one of: <<LABELS>>. Image 1 is
candidate 1, image 2 is candidate 2, and so on. An image holds up to three zoomed tiles of the
same candidate taken from different moments of the video (captions "n: label (1/3)", "(2/3)"...).
The green frame in each tile surrounds the candidate at that moment. Judge only what is inside
the green frames.

For every candidate, decide if it really is that label:
- true only if at least one tile shows it clearly, and the tiles agree: the same small part in
  the same place on the object being repaired or built.
- false if the frames hold something else (a hole, a mark in the wood, a reflection, a sticker,
  a finger, a loose part lying around, empty space), if they jump between different things, or
  if no tile shows it clearly.
- When in doubt, say false. A missed fastener is better than one that does not exist.

Return one entry per candidate, in order, with "n" equal to the candidate number.
