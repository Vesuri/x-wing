# P8 frames fixture (docs/perf-method.md): the combat film (m17) or the intro's Star
# Destroyer scene on the image that runs, driven by a KEYS script (tools/perf_film.py)
# that marks the window start with `shot`. From the mark: the PAL field at each of the next FRAMES visits to the
# scene's frame label @LABEL@ (the film: reference/milestones.csv `frame`), one gdb
# stop per frame outside any capture, then a 100-field instruction profile.
# @FRAMES@, @LABEL@ and @OUT@ are filled by tools/perf_film.py.
set pagination off
set confirm off
break plat_exit
commands
  silent
  printf "XWING_PERF_EXIT\n"
  quit 1
end
break *rt_stop
commands
  silent
  x/s *(char **)($sp+4)
  quit 1
end
break amiga_start_return
commands
  silent
  printf "XWING_PROGRAM_RETURNED %d\n", *(int *)($sp+4)
  quit 1
end
break amiga_script_mark
continue
delete $bpnum
printf "WINDOW_MARK field %u presents %u\n", amiga_frames, amiga_presents
break @LABEL@
set $n = 0
while $n < @FRAMES@
  continue
  printf "FRAME %d field %u\n", $n, amiga_frames
  set $n = $n + 1
end
delete $bpnum
printf "PROFILE_START field %u\n", amiga_frames
monitor profile 100 "" "@OUT@"
printf "PROFILE_END field %u\n", amiga_frames
printf "XWING_PERF_OK\n"
quit 0
