"use client";

import { useState, useCallback, useEffect } from "react";

export const DEFAULT_SPACE_TAG = "default";
const SPACE_PARAM = "space";

/**
 * Read the selected space tag from URL search params.
 * Uses URLSearchParams directly (no Suspense boundary needed).
 */
function getSpaceFromUrl(): string {
  if (typeof window === "undefined") return DEFAULT_SPACE_TAG;
  const params = new URLSearchParams(window.location.search);
  return params.get(SPACE_PARAM) ?? DEFAULT_SPACE_TAG;
}

/**
 * Update the URL's space param without a full navigation.
 */
function updateUrlSpace(tag: string) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (tag === DEFAULT_SPACE_TAG) {
    url.searchParams.delete(SPACE_PARAM);
  } else {
    url.searchParams.set(SPACE_PARAM, tag);
  }
  window.history.replaceState(null, "", url.toString());
}

export function useSelectedSpace() {
  const [selectedSpaceTag, setSelectedSpaceTagState] = useState(getSpaceFromUrl);

  // Sync with browser back/forward
  useEffect(() => {
    const handlePopState = () => setSelectedSpaceTagState(getSpaceFromUrl());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const setSelectedSpaceTag = useCallback((tag: string) => {
    updateUrlSpace(tag);
    setSelectedSpaceTagState(tag);
  }, []);

  return { selectedSpaceTag, setSelectedSpaceTag };
}
