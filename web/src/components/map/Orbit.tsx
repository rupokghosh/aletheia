/**
 * NISAR's orbit drawn around the globe: a thin line from pole to pole with the satellite moving along it.
 * It is to scale (747 km above a planet of radius 6,371 km, so 1.12 planet radii) and nearly polar, as the
 * real orbit is; it is not the satellite's live position.
 *
 * The drawing is in "planet units" (the planet's radius is 100) and CSS sizes and places it over the globe.
 * There are two copies. The one behind the map shows where the orbit passes behind the planet, which hides
 * it. The one in front of the map is cut to the near half, so the satellite crosses the face of the planet
 * and then disappears behind it.
 */
const PATH = "M 0 -112 A 34 112 0 1 1 0 112 A 34 112 0 1 1 0 -112";

export function Orbit({ half }: { half: "back" | "front" }) {
  return (
    <svg className={`orbit orbit-${half}`} viewBox="-150 -150 300 300" aria-hidden="true">
      {half === "front" ? (
        <defs>
          <clipPath id="orbit-near-half">
            <rect x="0" y="-150" width="150" height="300" />
          </clipPath>
        </defs>
      ) : null}
      <g transform="rotate(14)">
        <g clipPath={half === "front" ? "url(#orbit-near-half)" : undefined}>
          <path d={PATH} className="orbit-line" />
          <g className="orbit-craft">
            <circle r="7" className="orbit-craft-halo" />
            <circle r="3" className="orbit-craft-body" />
            <animateMotion dur="28s" repeatCount="indefinite" path={PATH} />
          </g>
        </g>
      </g>
    </svg>
  );
}
