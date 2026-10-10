// Position against the viewport, independently of the app container's height.
export function datePopoverPosition(anchor, size, viewport) {
  const margin = 12, gap = 8;
  const maxHeight = Math.max(0, viewport.height - margin * 2);
  const height = Math.min(size.height, maxHeight);
  const width = Math.min(size.width, Math.max(0, viewport.width - margin * 2));
  const left = Math.max(margin, Math.min(anchor.left, viewport.width - width - margin));
  const below = anchor.bottom + gap;
  const above = anchor.top - gap - height;
  const top = below + height <= viewport.height - margin ? below
    : above >= margin ? above : Math.max(margin, viewport.height - height - margin);
  return { left, top, maxHeight };
}
