"use client";

import { useRef } from "react";
import { useServerInsertedHTML } from "next/navigation";

import { THEME_BOOT_SCRIPT } from "@/lib/theme";

/**
 * Stamps `data-theme` on `<html>` before first paint, without putting a `<script>` in the
 * React tree. React 19 warns (and the Next overlay errors) on client-rendered script tags
 * because they never execute; `next/script` `beforeInteractive` queues after
 * DOMContentLoaded, which flashes the wrong theme. `useServerInsertedHTML` writes the
 * inline script into `<head>` on the server only.
 */
export default function ThemeBoot() {
  const inserted = useRef(false);
  useServerInsertedHTML(() => {
    if (inserted.current) return null;
    inserted.current = true;
    return <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />;
  });
  return null;
}
