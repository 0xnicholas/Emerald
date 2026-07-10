"use client";

import { Search as SearchIcon, Loader, X, Clock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useState, useRef, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";

const RECENT_SEARCHES_KEY = "emerald:recent-searches";
const MAX_RECENT = 6;

interface SearchBarProps {
  onSearch: (q: string) => void;
  onTagFilter?: (tag: string) => void;
  loading?: boolean;
  placeholder?: string;
  autoSearch?: boolean; // search on typing (debounced)
}

function readRecentSearches(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_SEARCHES_KEY);
    return raw ? JSON.parse(raw).filter((x: unknown) => typeof x === "string") : [];
  } catch { return []; }
}

function saveRecentSearch(q: string) {
  if (!q.trim()) return;
  try {
    const next = [q.trim(), ...readRecentSearches().filter((s) => s !== q)].slice(0, MAX_RECENT);
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(next));
  } catch { /* noop */ }
}

export function SearchBar({
  onSearch,
  onTagFilter,
  loading,
  placeholder = "搜索记忆…",
  autoSearch = false,
}: SearchBarProps) {
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setRecentSearches(readRecentSearches());
  }, []);

  // Click outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setFocused(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const submitSearch = useCallback((q: string) => {
    const trimmed = q.trim();
    setValue(trimmed);
    if (trimmed) saveRecentSearch(trimmed);
    setRecentSearches(readRecentSearches());
    onSearch(trimmed);
    setFocused(false);
  }, [onSearch]);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setValue(v);
    if (autoSearch) {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onSearch(v.trim());
      }, 300);
    }
  }, [autoSearch, onSearch]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submitSearch(value);
    }
    if (e.key === "Escape") {
      setFocused(false);
      inputRef.current?.blur();
    }
  }, [value, submitSearch]);

  const handleClear = useCallback(() => {
    setValue("");
    onSearch("");
    inputRef.current?.focus();
  }, [onSearch]);

  const showDropdown = focused && !value.trim() && recentSearches.length > 0;

  return (
    <div className="relative">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted" />
          <Input
            ref={inputRef}
            value={value}
            onChange={handleChange}
            onFocus={() => setFocused(true)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="pl-9 pr-8"
          />
          {value && (
            <button
              onClick={handleClear}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-faint hover:text-fg-muted"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <Button
          type="button"
          onClick={() => submitSearch(value)}
          disabled={loading || !value.trim()}
          className="shrink-0"
        >
          {loading ? (
            <Loader className="h-4 w-4 animate-spin" />
          ) : (
            "搜索"
          )}
        </Button>
      </div>

      {/* Suggestions dropdown */}
      {showDropdown && (
        <div
          ref={dropdownRef}
          className="absolute top-full left-0 right-0 mt-1 z-50 rounded-xl border border-surface-border bg-surface-card shadow-lg backdrop-blur-xl overflow-hidden"
        >
          <div className="px-3 py-2 text-[10px] uppercase tracking-wider text-fg-faint font-medium flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            Recent searches
          </div>
          {recentSearches.map((q) => (
            <button
              key={q}
              onClick={() => submitSearch(q)}
              className="flex items-center gap-3 w-full px-3 py-2 text-sm text-fg-primary hover:bg-surface-hover transition-colors text-left"
            >
              <SearchIcon className="h-3.5 w-3.5 text-fg-faint shrink-0" />
              <span className="truncate">{q}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
