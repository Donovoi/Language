# MVP

## Goal

Build a multi-speaker, focus-aware live translation system that can:

- track multiple speakers in a scene
- prioritize them dynamically
- present translated captions per speaker lane
- return metadata needed for translated-audio mixing

## Non-goals

The MVP does **not** promise:

- perfect universal room translation
- perfect distance estimation
- legally authoritative interpretation
- perfect source-voice cloning

## Initial operating modes

### Focus mode
Translate and emphasize the most relevant speaker.

### Crowd mode
Track many speakers but only elevate the top subset into the translated audio mix.

### Locked mode
Temporarily bias toward a user-selected speaker.

## First milestones

1. Local scene simulation
2. Speaker timeline UI
3. Backend event stream
4. Priority scoring
5. Basic end-to-end transport
