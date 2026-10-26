-- Pinned System 7.5.5 / Macintosh Quadra 700 reference: configure the fresh volume
-- through the original control panels, restart, and launch the original demo.
-- Original instructions execute unmodified; this script only drives the mouse/keyboard.
io.stdout:setvbuf('no')
local run=assert(os.getenv('XWING_REFERENCE_RUN'),'REFERENCE / RUN REQUIRED')
local mac=dofile('tools/mame_mac_input.lua')
local mem=manager.machine.devices[':maincpu'].spaces.program
local app='X-Wing'
local finished=false
local function fail(reason)
 if finished then return end
 finished=true;print('FAIL REFERENCE / '..tostring(reason));manager.machine:exit()
end
local function shot(label)
 manager.machine.video:snapshot();print('SNAPSHOT '..label)
end
local function finder()
 assert(mac.wait_for('Finder',function()return mac.frontmost()=='Finder'end,9000),'FINDER')
 mac.wait(600)
end
-- Main GDevice pixel depth; handles are full 32-bit pointers once 32-bit addressing is on.
local function depth(mask)
 local gd=mem:readv_u32(mem:readv_u32(0x8a4)&mask)&mask
 local pm=mem:readv_u32(mem:readv_u32(gd+22)&mask)&mask
 return mem:readv_u16(pm+32)
end
mac.run(function()
 local ok,err=pcall(function()
  -- First boot: the fresh volume starts in 24-bit mode with a 1-bit display.
  finder()
  assert(mem:readv_u16(0x15a)==0x755,'SYSTEM VERSION')
  assert(mem:readv_u8(0xcb2)==0,'FIRST BOOT ADDRESSING')
  mac.menu(20,60);mac.wait(300)                       -- Apple menu > Control Panels
  mac.type('Memory');mac.press('o',{mac.CMD});mac.wait(400)
  assert(mac.mouse_to(170,238));mac.click();mac.wait(120)   -- 32-Bit Addressing: On
  shot('memory-panel')
  mac.press('w',{mac.CMD});mac.wait(200)
  mac.type('Monitors');mac.press('o',{mac.CMD});mac.wait(400)
  assert(mac.mouse_to(115,105));mac.click();mac.wait(60)    -- Colors
  assert(mac.mouse_to(172,119));mac.click();mac.wait(300)   -- 256
  shot('monitors-panel')
  assert(depth(0xffffff)==8,'DISPLAY DEPTH BEFORE RESTART')
  -- Close Monitors and Control Panels so the next boot's desktop takes type-select.
  mac.press('w',{mac.CMD});mac.wait(200);mac.press('w',{mac.CMD});mac.wait(200)
  mac.menu(232,123)                                  -- Special > Restart
  -- Second boot: 32-bit addressing is now in effect.
  assert(mac.wait_for('restart',function()return mac.frontmost()~='Finder'end,3000),'RESTART')
  finder()
  assert(mem:readv_u8(0xcb2)~=0,'32-BIT ADDRESSING')
  assert(depth(0xffffffff)==8,'DISPLAY DEPTH AFTER RESTART')
  print('CONFIGURED 32-bit addressing, 640x480x8')
  shot('second-boot')
  -- Launch: type-select the folder on the desktop, open it, type-select the application.
  mac.type('X');mac.press('o',{mac.CMD});mac.wait(400)
  mac.type(app);mac.wait(60);mac.press('o',{mac.CMD})
  assert(mac.wait_for('application',function()return mac.frontmost()==app end,3000),'APPLICATION')
  print('APPLICATION_FRONTMOST '..app)
  for i=1,12 do
   mac.wait(600)
   assert(mac.frontmost()==app,'APPLICATION QUIT')
   shot(string.format('running-%02d',i))
  end
  print('REFERENCE_RUNNING '..app)
 end)
 if not ok then fail(err) else finished=true;manager.machine:exit() end
end)
