import test from 'node:test';
import assert from 'node:assert/strict';
import { datePopoverPosition } from './datePopover.js';

test('calendar sits below its trigger when the complete panel fits', () => {
  assert.deepEqual(datePopoverPosition({ left: 300, top: 120, bottom: 160 },
    { width: 600, height: 470 }, { width: 1400, height: 900 }),
  { left: 300, top: 168, maxHeight: 876 });
});
test('calendar flips above a low trigger and stays within the right edge', () => {
  assert.deepEqual(datePopoverPosition({ left: 1100, top: 570, bottom: 610 },
    { width: 600, height: 400 }, { width: 1400, height: 680 }),
  { left: 788, top: 162, maxHeight: 656 });
});
test('calendar fits a short viewport even when neither anchored side has enough space', () => {
  const viewport = { width: 1000, height: 680 }, size = { width: 600, height: 470 };
  const position = datePopoverPosition({ left: 300, top: 300, bottom: 340 }, size, viewport);
  assert.equal(position.top, 198);
  assert.ok(position.top + size.height <= viewport.height - 12);
});
test('small screens bound panel height for scrolling and leave a margin on each edge', () => {
  const position = datePopoverPosition({ left: 240, top: 140, bottom: 180 },
    { width: 340, height: 470 }, { width: 320, height: 240 });
  assert.deepEqual(position, { left: 12, top: 12, maxHeight: 216 });
});
