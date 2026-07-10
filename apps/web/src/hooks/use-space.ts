"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useCallback } from "react";

export const DEFAULT_SPACE_TAG = "default";
const SPACE_PARAM = "space";

export function useSelectedSpace() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const selectedSpaceTag = searchParams.get(SPACE_PARAM) ?? DEFAULT_SPACE_TAG;

  const setSelectedSpaceTag = useCallback(
    (tag: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (tag === DEFAULT_SPACE_TAG) {
        params.delete(SPACE_PARAM);
      } else {
        params.set(SPACE_PARAM, tag);
      }
      const next = params.toString();
      router.replace(next ? `?${next}` : window.location.pathname, { scroll: false });
    },
    [searchParams, router]
  );

  return { selectedSpaceTag, setSelectedSpaceTag };
}
