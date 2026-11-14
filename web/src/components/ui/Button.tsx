import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

/** Pills: solid black for the one main action, white with a hairline for the rest, plain text for the least. */
const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-black disabled:bg-raised-2 disabled:text-ink-3",
  secondary: "border border-line-strong bg-panel text-ink hover:bg-raised disabled:text-ink-3 disabled:hover:bg-panel",
  ghost: "text-ink-2 hover:bg-raised hover:text-ink disabled:text-ink-3 disabled:hover:bg-transparent",
};

const SIZES: Record<Size, string> = {
  sm: "min-h-9 gap-1.5 px-3.5 text-sm",
  md: "min-h-11 gap-2 px-5 text-[15px]",
};

export function Button({ variant = "secondary", size = "md", className = "", type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={`press inline-flex shrink-0 items-center justify-center rounded-full whitespace-nowrap ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
}
