import type { ReactNode, SVGProps } from "react";

type IconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function icon(paths: ReactNode) {
  return function Icon({ width = 16, height = 16, ...rest }: IconProps) {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 16 16"
        width={width}
        height={height}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        {...rest}
      >
        {paths}
      </svg>
    );
  };
}

export const SearchIcon = icon(
  <>
    <circle cx="7" cy="7" r="4.25" />
    <path d="m10.25 10.25 3.25 3.25" />
  </>,
);

export const DrawIcon = icon(
  <>
    <path d="M2.5 5V3.5a1 1 0 0 1 1-1H5M11 2.5h1.5a1 1 0 0 1 1 1V5M13.5 11v1.5a1 1 0 0 1-1 1H11M5 13.5H3.5a1 1 0 0 1-1-1V11" />
    <path d="M7 2.5h2M7 13.5h2M2.5 7v2M13.5 7v2" />
  </>,
);

export const LayersIcon = icon(
  <>
    <path d="m8 2 6 3-6 3-6-3 6-3Z" />
    <path d="m2 8 6 3 6-3M2 11l6 3 6-3" />
  </>,
);

export const InfoIcon = icon(
  <>
    <circle cx="8" cy="8" r="6" />
    <path d="M8 7.25v3.5M8 5.1v.05" />
  </>,
);

export const WarningIcon = icon(
  <>
    <path d="M8 2.25 14.25 13H1.75L8 2.25Z" />
    <path d="M8 6.5v3M8 11.2v.05" />
  </>,
);

export const CloseIcon = icon(<path d="m3.5 3.5 9 9M12.5 3.5l-9 9" />);
export const CheckIcon = icon(<path d="m3 8.5 3.25 3.25L13 4.75" />);
export const ChevronLeftIcon = icon(<path d="M10 3.5 5.5 8l4.5 4.5" />);
export const ChevronRightIcon = icon(<path d="M6 3.5 10.5 8 6 12.5" />);
export const ChevronDownIcon = icon(<path d="M3.5 6 8 10.5 12.5 6" />);

export const CopyIcon = icon(
  <>
    <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
    <path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
  </>,
);

export const DownloadIcon = icon(
  <>
    <path d="M8 2.5v8M4.75 7.5 8 10.75l3.25-3.25" />
    <path d="M2.75 13.25h10.5" />
  </>,
);

export const ExternalIcon = icon(
  <>
    <path d="M9 2.75h4.25V7M13.25 2.75 7.5 8.5" />
    <path d="M11.25 9.5v2.75a1 1 0 0 1-1 1h-6.5a1 1 0 0 1-1-1v-6.5a1 1 0 0 1 1-1H6.5" />
  </>,
);

export const PlayIcon = icon(<path d="M4.5 3v10l8.5-5-8.5-5Z" fill="currentColor" />);
export const PauseIcon = icon(<path d="M5 3v10M11 3v10" strokeWidth={2.25} />);

export const TargetIcon = icon(
  <>
    <circle cx="8" cy="8" r="4.25" />
    <path d="M8 1.5v2.25M8 12.25v2.25M1.5 8h2.25M12.25 8h2.25" />
  </>,
);
