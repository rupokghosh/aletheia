"use client";

import { useEffect, useId, useRef, useState } from "react";
import { CloseIcon, SearchIcon } from "@/components/ui/icons";
import { placeBounds, searchPlaces, type Place } from "@/lib/geocode";
import { useApp } from "@/lib/store";

type Status = "idle" | "loading" | "ready" | "error";

/** Place search. Requests wait for a pause in typing, and stale ones are cancelled. */
export function PlaceSearch() {
  const { dispatch } = useApp();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 3) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setStatus("loading");
      searchPlaces(trimmed, controller.signal)
        .then((found) => {
          setPlaces(found);
          setActive(0);
          setStatus("ready");
        })
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) setStatus("error");
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const choose = (place: Place) => {
    dispatch({ type: "placeName", placeName: place.name });
    dispatch({ type: "flyTo", bbox: placeBounds(place) });
    setQuery(place.name);
    setOpen(false);
    inputRef.current?.blur();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open || places.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % places.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index - 1 + places.length) % places.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(places[active]);
    }
  };

  const showList = open && query.trim().length >= 3;

  return (
    <div>
      <div className="flex h-11 items-center gap-2.5 rounded-xl border border-line-strong bg-panel pr-1.5 pl-3.5 focus-within:border-ink">
        <SearchIcon className="shrink-0 text-ink-3" />
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-label="Search for a place, or enter latitude, longitude"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && places[active] ? `${listId}-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder="Search for a place"
          className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        {query ? (
          <button
            type="button"
            aria-label="Clear the search"
            className="press grid size-8 shrink-0 place-items-center rounded-full text-ink-3 hover:bg-raised hover:text-ink"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              setQuery("");
              setPlaces([]);
              setStatus("idle");
              inputRef.current?.focus();
            }}
          >
            <CloseIcon />
          </button>
        ) : null}
      </div>

      {/* The list is part of the page flow, so the card cannot clip it. No animation: it follows the keyboard. */}
      {showList ? (
        <div
          className="mt-2 overflow-hidden rounded-xl border border-line"
          // Keeps focus in the input so the list stays open while it is clicked.
          onMouseDown={(event) => event.preventDefault()}
        >
          <ul id={listId} role="listbox" aria-label="Places">
            {places.map((place, index) => (
              <li
                key={place.id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                className={`cursor-pointer px-3.5 py-2 ${index === active ? "bg-raised" : ""}`}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(place)}
              >
                <p className="truncate text-[15px] text-ink">{place.name}</p>
                {place.detail ? <p className="truncate text-[13px] text-ink-3">{place.detail}</p> : null}
              </li>
            ))}
          </ul>
          {status !== "ready" || places.length === 0 ? (
            <p className="px-3.5 py-2 text-sm text-ink-3" role="status">
              {status === "error"
                ? "Place search is unavailable. Enter latitude, longitude instead."
                : status === "ready"
                  ? "No place found."
                  : "Searching"}
            </p>
          ) : null}
          <p className="border-t border-line px-3.5 py-1.5 text-xs text-ink-3">
            Search by{" "}
            <a className="underline underline-offset-2" href="https://photon.komoot.io" target="_blank" rel="noreferrer">
              Photon
            </a>
            , data ©{" "}
            <a className="underline underline-offset-2" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
              OpenStreetMap
            </a>{" "}
            contributors
          </p>
        </div>
      ) : null}
    </div>
  );
}
