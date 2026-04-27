# Contract: wake_screen restores idle image after blank

Bug: bd auto-kj-edi

## Behaviors

- [ ] When the screen is blanked (i.e. `_idle_proc` is the live black mpv) and `wake_screen()` is called, the black mpv is terminated and a new mpv is spawned with the idle hero image.
  - Verify: Player has `_screen_blanked=True` with a live mock `_idle_proc`. After `wake_screen()`, the original proc has `terminate()` called, and a new Popen call is made with `_IDLE_IMAGE` in its args.

- [ ] After `_blank_screen()` followed by `_show_idle_once()`, the idle image is shown (i.e. the black mpv is replaced).
  - Verify: With Popen mocked, `_blank_screen()` then `_show_idle_once()`. Check that the previous proc was terminated and a new Popen used `_IDLE_IMAGE`.

- [ ] `_show_idle_once()` is still a no-op when the idle image is already being shown (no thrash).
  - Verify: `_show_idle_once()` then `_show_idle_once()` again. Second call must not spawn another Popen and must not terminate the first proc.

## Out of scope
- Refactor of the `show_idle_image` cycle thread timing.
- Wakeword pipeline.
