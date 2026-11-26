/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SHOW_STEAM_TAB?: string;
  readonly VITE_SHOW_APPLE_MARKETS_TAB?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
