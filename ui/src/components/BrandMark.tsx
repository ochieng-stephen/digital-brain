// The app logomark: the actual pen-and-ink brain⇄chip drawing, extracted from the source art and
// keyed to transparency (no square background). The silicon half is filled by the current domain's
// gradient via a CSS mask, so the real drawing recolors when you switch brains.
//
// The silicon half also IS the live indicator: when the app is not connected to the backend
// (`live={false}`) it desaturates to grey — the colour drains out of the machine half. `connecting`
// adds a soft breathe while the client is still reaching the brain.

interface Props {
  live?: boolean;
  connecting?: boolean;
}

export default function BrandMark({ live = true, connecting = false }: Props) {
  return (
    <span
      className={"brandmark-logo" + (connecting ? " connecting" : "")}
      data-live={live ? "true" : "false"}
      role="img"
      aria-label={live ? "Digital Brain — live" : "Digital Brain — offline"}
    />
  );
}
