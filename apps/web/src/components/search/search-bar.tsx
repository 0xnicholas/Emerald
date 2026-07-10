"use client";

import { Search as SearchIcon, Loader } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useState } from "react";

interface SearchBarProps {
  onSearch: (q: string) => void;
  loading?: boolean;
  placeholder?: string;
}

export function SearchBar({
  onSearch,
  loading,
  placeholder = "搜索记忆…",
}: SearchBarProps) {
  const [value, setValue] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch(value);
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <div className="relative flex-1">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          className="pl-9"
        />
      </div>
      <Button type="submit" disabled={loading || !value.trim()}>
        {loading ? (
          <Loader className="h-4 w-4 animate-spin" />
        ) : (
          "搜索"
        )}
      </Button>
    </form>
  );
}
