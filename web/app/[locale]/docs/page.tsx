import { redirect } from "@/i18n/navigation"
import { routing } from "@/i18n/routing"

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

// Docs root has no content of its own — bounce to the canonical entry
// page (Introduction). Using next-intl's redirect keeps the locale prefix
// in the resulting URL.
export default async function DocsRoot({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  redirect({ href: "/docs/introduction", locale })
}
