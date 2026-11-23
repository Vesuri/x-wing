# P9 save and exit scenario (tools/test_save_exit.py, docs/release.md): the image runs
# from a Shell with a KEYS script that registers the pilot LUKE, saves it at the
# concourse (m06) and leaves by the concourse's exit (m16). It must reach m16's
# milestone point, the exit's INT 21h at XWING.EXE+1660 (R_01660), then plat_exit with
# the game's exit code, then the program's return to the Shell. A runtime stop, an exit
# before the milestone point or a return before plat_exit fails.
set pagination off
set confirm off
break *rt_stop
commands
  silent
  printf "XWING_STOP %s\n", *(char **)($sp+4)
  quit 1
end
break plat_exit
set $early_exit = $bpnum
commands
  silent
  printf "XWING_EARLY_EXIT %d\n", *(int *)($sp+4)
  quit 1
end
break amiga_start_return
commands
  silent
  printf "XWING_PROGRAM_RETURNED %d\n", *(int *)($sp+4)
  printf "TICKS counted %u posted %u\n", rt_irq_counted, amiga_ticks
  detach
  quit 0
end
break R_01660
continue
delete $bpnum
delete $early_exit
printf "XWING_EXIT_POINT field %u\n", amiga_frames
break plat_exit
continue
delete $bpnum
printf "XWING_EXIT_CODE %d\n", *(int *)($sp+4)
continue
printf "XWING_NO_RETURN\n"
quit 1
