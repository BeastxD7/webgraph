"use client";

import { PRESETS } from "@/lib/kg";
import { useApiKey, useProviderPrefs } from "@/lib/kgSettings";

import { Field, Note, Panel, Select, TextInput } from "./fields";

/**
 * Which model reads the site, and with whose key.
 *
 * The key is typed here and sent in the body of each build or ask request; the API uses it
 * for that request and stores nothing -- there is no account, no server-side settings file,
 * and the API redacts the field from every error it echoes. By default the key lives in this
 * page's memory and is gone on reload; "remember in this browser" keeps it in localStorage on
 * this machine only. The panel says all of that in plain words because a reader pasting a
 * key deserves to know where it goes.
 */
export default function ProviderPanel({ disabled = false }: { disabled?: boolean }) {
  const [prefs, setPrefs, loaded] = useProviderPrefs();
  const [apiKey, remembered, setKey, setRemember] = useApiKey();
  const preset = PRESETS.find((p) => p.id === prefs.preset) ?? PRESETS[0]!;
  const needsKey = !preset.local && preset.id !== "custom";

  return (
    <Panel
      title="Model"
      lede={
        <>
          Bring your own key, run a local model, or point at any OpenAI-compatible endpoint.
          Nothing here is stored on the server.
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Provider">
          <Select
            value={prefs.preset}
            disabled={disabled || !loaded}
            onChange={(event) => {
              const next = PRESETS.find((p) => p.id === event.target.value) ?? PRESETS[0]!;
              setPrefs({ preset: next.id, base_url: next.base_url });
            }}
          >
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Endpoint" hint={preset.kind !== "openai-compatible" ? `${preset.kind} API` : "OpenAI-compatible chat completions"}>
          <TextInput
            type="url"
            value={prefs.base_url}
            disabled={disabled}
            placeholder="https://host/v1"
            onChange={(event) => setPrefs({ base_url: event.target.value })}
            className="font-mono text-code"
          />
        </Field>

        <Field label="Model" hint={`e.g. ${preset.example_model}`}>
          <TextInput
            value={prefs.model}
            disabled={disabled}
            placeholder={preset.example_model}
            onChange={(event) => setPrefs({ model: event.target.value })}
            className="font-mono text-code"
          />
        </Field>

        <Field label="Answer model" hint="Optional. A stronger model for answers; the reading model does extraction.">
          <TextInput
            value={prefs.answer_model}
            disabled={disabled}
            placeholder="same as model"
            onChange={(event) => setPrefs({ answer_model: event.target.value })}
            className="font-mono text-code"
          />
        </Field>

        <Field
          label="API key"
          className="sm:col-span-2"
          hint={
            needsKey ? (
              <>
                Sent only inside each build or ask request, over the connection to your own API,
                and used for that request alone: the server never writes it to disk, a settings
                file or a log, and redacts it from every error it returns. Leave it empty to use
                the API&rsquo;s <code className="font-mono">{preset.key_env}</code> environment variable.
              </>
            ) : (
              <>Local servers need none. Any value typed here is still sent only with each request and never stored server-side.</>
            )
          }
        >
          <TextInput
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            disabled={disabled}
            placeholder={needsKey ? `${preset.key_env} or paste a key` : "not needed"}
            onChange={(event) => setKey(event.target.value)}
            className="font-mono text-code"
          />
        </Field>

        <label className="flex items-start gap-2 text-caption text-muted sm:col-span-2">
          <input
            type="checkbox"
            checked={remembered}
            disabled={disabled}
            onChange={(event) => setRemember(event.target.checked)}
            className="mt-0.5 size-4 accent-accent"
          />
          <span>
            Remember the key in this browser (localStorage on this machine). Off by default: the
            key lives in this page&rsquo;s memory and is gone on reload.
          </span>
        </label>

        <Field label="Parallel requests" hint="Lower it for a local server; the engine caps at 16." className="sm:max-w-[12rem]">
          <TextInput
            type="number"
            min={1}
            max={16}
            value={prefs.max_concurrency}
            disabled={disabled}
            onChange={(event) => setPrefs({ max_concurrency: Math.max(1, Math.min(16, Number(event.target.value) || 1)) })}
          />
        </Field>
      </div>
      {!prefs.model && (
        <div className="mt-3">
          <Note tone="warn">
            No model named. The API falls back to its <code className="font-mono">WEBGRAPH_LLM_MODEL</code>; if that
            is unset too, the build is refused before any request is made.
          </Note>
        </div>
      )}
    </Panel>
  );
}
