import { Composition } from "remotion";
import { Film } from "./Film";
import { FPS, HEIGHT, TOTAL, WIDTH } from "./timeline";

export function Root() {
  return (
    <Composition
      id="Film"
      component={Film}
      width={WIDTH}
      height={HEIGHT}
      fps={FPS}
      durationInFrames={TOTAL}
      defaultProps={{ site: "aletheia-five-tawny.vercel.app" }}
    />
  );
}
