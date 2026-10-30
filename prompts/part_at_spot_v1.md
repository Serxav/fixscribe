You are an object grounding expert looking at a close-up of a repair.

Context: <<CONTEXT>>

The guide calls the part of this step: <<PART>>. The guide can be wrong.

A small magenta cross at the centre of the image marks the spot where the person's tool or fingers
touch during this step. Ignore the cross itself.

Answer about the one physical part under the cross:
- `visible`: false if you cannot clearly see a distinct part there (only blur, shadow, a hand, a tool).
- `name`: the plain name of what you really see, in two or three words, such as "metal bracket" or
  "flex cable connector". Use the guide's word only if that is what it looks like.
- `x_min`, `y_min`, `x_max`, `y_max`: the tightest box around that one part, on a 0-1000 grid of this
  image. It must contain the cross. Do not include neighbouring parts, the tool or the hand.
