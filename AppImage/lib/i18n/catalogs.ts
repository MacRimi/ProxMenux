import enMessages from "../../messages/en/common.json"
import deMessages from "../../messages/de/common.json"
import esMessages from "../../messages/es/common.json"
import frMessages from "../../messages/fr/common.json"
import itMessages from "../../messages/it/common.json"
import ptMessages from "../../messages/pt/common.json"
import skMessages from "../../messages/sk/common.json"
import svMessages from "../../messages/sv/common.json"
import type { LanguageCode } from "./languages"

type MessageTree = Record<string, unknown>

// Shared by React translations and error handling outside React hooks.
export const MESSAGE_CATALOG: Record<LanguageCode, MessageTree> = {
  en: enMessages as MessageTree,
  de: deMessages as MessageTree,
  es: esMessages as MessageTree,
  fr: frMessages as MessageTree,
  it: itMessages as MessageTree,
  pt: ptMessages as MessageTree,
  sk: skMessages as MessageTree,
  sv: svMessages as MessageTree,
}
