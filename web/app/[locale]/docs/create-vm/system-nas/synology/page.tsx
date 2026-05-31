"use client"

import Image from "next/image"
import { Link } from "@/i18n/navigation"
import { useState } from "react"
import { Github, ExternalLink } from "lucide-react"
import { useTranslations, useMessages } from "next-intl"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

type LoaderKey = "arc" | "rr" | "tinycore"

type LoaderLink = { name: string; url: string }
type DefaultRow = { param: string; valueRich: string }
type AdvancedRow = { param: string; optionsRich: string }
type ItemAltCaption = { alt: string; caption: string }
type DocLink = { label: string; url: string }
type RelatedItem = { href: string; label: string; tail: string }

export default function SynologyPage() {
  const [activeLoader, setActiveLoader] = useState<LoaderKey>("arc")
  const t = useTranslations("docs.createVm.systemNas.synology")
  const messages = useMessages() as unknown as {
    docs: {
      createVm: {
        systemNas: {
          synology: {
            supportedLoaders: { loaders: LoaderLink[] }
            config: { defaultRowsRich: DefaultRow[]; advancedRowsRich: AdvancedRow[] }
            storagePlan: { virtualItemsRich: string[]; importItemsRich: string[]; pciItemsRich: string[] }
            vmCreation: { itemsRich: string[] }
            step3: { arc: ItemAltCaption[]; rr: ItemAltCaption[]; tinycore: ItemAltCaption[] }
            step4: { rr: ItemAltCaption[]; tinycore: ItemAltCaption[] }
            tips: { docLinks: DocLink[] }
            related: { itemsRich: RelatedItem[] }
          }
        }
      }
    }
  }
  const s = messages.docs.createVm.systemNas.synology
  const loaders = s.supportedLoaders.loaders
  const defaultRows = s.config.defaultRowsRich
  const advancedRows = s.config.advancedRowsRich
  const virtualItems = s.storagePlan.virtualItemsRich
  const importItems = s.storagePlan.importItemsRich
  const pciItems = s.storagePlan.pciItemsRich
  const vmCreationItems = s.vmCreation.itemsRich
  const step3Arc = s.step3.arc
  const step3Rr = s.step3.rr
  const step3Tc = s.step3.tinycore
  const step4Rr = s.step4.rr
  const step4Tc = s.step4.tinycore
  const docLinks = s.tips.docLinks
  const relatedItems = s.related.itemsRich

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const gpuLink = (chunks: React.ReactNode) => (
    <a href="/docs/hardware/gpu-vm-passthrough" className="text-blue-600 hover:underline">
      {chunks}
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={30}
        scriptPath="vm/synology.sh"
      />

      <Callout variant="info" title={t("whatThisDoes.title")}>
        {t.rich("whatThisDoes.bodyRich", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("supportedLoaders.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("supportedLoaders.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {loaders.map((l) => (
          <li key={l.url}>
            <a
              href={l.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline inline-flex items-center gap-1"
            >
              {l.name} <ExternalLink className="h-3 w-3" />
            </a>
          </li>
        ))}
        <li>{t.rich("supportedLoaders.customRich", { strong, code })}</li>
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("config.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("config.intro")}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("config.defaultHeading")}</h3>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("config.headerParam")}</th>
              <th className="px-4 py-2 font-semibold">{t("config.headerValue")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {defaultRows.map((row, idx) => (
              <tr key={row.param}>
                <td className="px-4 py-2">{row.param}</td>
                <td className="px-4 py-2">{t.rich(`config.defaultRowsRich.${idx}.valueRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("config.advancedHeading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("config.advancedIntro")}</p>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("config.headerParam")}</th>
              <th className="px-4 py-2 font-semibold">{t("config.headerOptions")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {advancedRows.map((row, idx) => (
              <tr key={row.param}>
                <td className="px-4 py-2">{row.param}</td>
                <td className="px-4 py-2">{t.rich(`config.advancedRowsRich.${idx}.optionsRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("storagePlan.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("storagePlan.introRich", { strong })}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.virtualHeading")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {virtualItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.virtualItemsRich.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.importHeading")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {importItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.importItemsRich.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4 md:col-span-2">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.pciHeading")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {pciItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.pciItemsRich.${idx}`, { code, em })}</li>
            ))}
          </ul>
        </div>
      </div>

      <Callout variant="info" title={t("storagePlan.resetCalloutTitle")}>
        {t.rich("storagePlan.resetCalloutBodyRich", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("gpu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("gpu.bodyRich", { link: gpuLink })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("loaderInstall.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("loaderInstall.intro1Rich", { strong })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("loaderInstall.intro2Rich", { strong, code })}</p>
      <p className="mb-2 text-gray-800 leading-relaxed">{t("loaderInstall.uploadIntro")}</p>
      <ImageCaption src="/vm/synology/add_loader.png" alt={t("loaderInstall.imageAlt")} caption={t("loaderInstall.imageCaption")} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vmCreation.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t.rich("vmCreation.introRich", { code })}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {vmCreationItems.map((_, idx) => (
          <li key={idx}>{t.rich(`vmCreation.itemsRich.${idx}`, { code, strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("stepByStep.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("stepByStep.intro")}</p>

      <Callout variant="warning" title={t("stepByStep.warnCalloutTitle")}>
        {t("stepByStep.warnCalloutBody")}
      </Callout>

      <div className="flex flex-wrap gap-2 my-6">
        {(["arc", "rr", "tinycore"] as LoaderKey[]).map((k) => (
          <button
            key={k}
            onClick={() => setActiveLoader(k)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeLoader === k
                ? "bg-blue-600 text-white"
                : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
            }`}
          >
            {t(`loaderLabels.${k}`)}
          </button>
        ))}
      </div>

      <StepSection n={1} title={t("step1.title")} stepLabel={t("stepBadge")}>
        <p className="mb-4 text-gray-800 leading-relaxed">{t("step1.intro")}</p>

        {activeLoader === "arc" && (
          <div className="flex flex-col space-y-8">
            <p className="text-gray-800 leading-relaxed">{t.rich("step1.arc.webRich", { strong, code })}</p>
            <ImageCaption src="/vm/synology/arc/arc_1_0_1.png" alt={t("step1.arc.webAlt")} caption={t("step1.arc.webCaption")} />
            <p className="text-gray-800 leading-relaxed">{t.rich("step1.arc.termRich", { strong })}</p>
            <ImageCaption src="/vm/synology/arc/arc_1_1_1.png" alt={t("step1.arc.termAlt")} caption={t("step1.arc.termCaption")} />
          </div>
        )}

        {activeLoader === "rr" && (
          <div className="flex flex-col space-y-8">
            <p className="text-gray-800 leading-relaxed">{t.rich("step1.rr.webRich", { strong, code })}</p>
            <ImageCaption src="/vm/synology/rr/rr_2_0_2.png" alt={t("step1.rr.webAlt")} caption={t("step1.rr.webCaption")} />
            <p className="text-gray-800 leading-relaxed">{t.rich("step1.rr.termRich", { strong, code })}</p>
            <ImageCaption src="/vm/synology/rr/rr_2_1_1.png" alt={t("step1.rr.termAlt")} caption={t("step1.rr.termCaption")} />
          </div>
        )}

        {activeLoader === "tinycore" && (
          <div className="flex flex-col space-y-8">
            <p className="text-gray-800 leading-relaxed">{t.rich("step1.tinycore.webRich", { strong, code })}</p>
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_0_1.png" alt={t("step1.tinycore.webAlt")} caption={t("step1.tinycore.webCaption")} />
            <p className="text-gray-800 leading-relaxed">{t.rich("step1.tinycore.termRich", { strong })}</p>
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_1_1.png" alt={t("step1.tinycore.termAlt")} caption={t("step1.tinycore.termCaption")} />
          </div>
        )}
      </StepSection>

      <StepSection n={2} title={t("step2.title")} stepLabel={t("stepBadge")}>
        <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("step2.introRich", { strong })}</p>
        {activeLoader === "arc" && (
          <ImageCaption src="/vm/synology/arc/arc_1_2_1.png" alt={t("step2.arc.alt")} caption={t("step2.arc.caption")} />
        )}
        {activeLoader === "rr" && (
          <ImageCaption src="/vm/synology/rr/rr_2_2_1.png" alt={t("step2.rr.alt")} caption={t("step2.rr.caption")} />
        )}
        {activeLoader === "tinycore" && (
          <ImageCaption src="/vm/synology/tinycore/tinycore_3_2_1.png" alt={t("step2.tinycore.alt")} caption={t("step2.tinycore.caption")} />
        )}
      </StepSection>

      <StepSection n={3} title={t("step3.title")} stepLabel={t("stepBadge")}>
        <p className="mb-4 text-gray-800 leading-relaxed">{t("step3.intro")}</p>
        {activeLoader === "arc" && (
          <div className="flex flex-col space-y-10">
            <ImageCaption src="/vm/synology/arc/arc_1_3_1.png" alt={step3Arc[0].alt} caption={step3Arc[0].caption} />
            <ImageCaption src="/vm/synology/arc/arc_1_3_2.png" alt={step3Arc[1].alt} caption={step3Arc[1].caption} />
          </div>
        )}
        {activeLoader === "rr" && (
          <div className="flex flex-col space-y-10">
            <ImageCaption src="/vm/synology/rr/rr_2_3_1.png" alt={step3Rr[0].alt} caption={step3Rr[0].caption} />
            <ImageCaption src="/vm/synology/rr/rr_2_3_2.png" alt={step3Rr[1].alt} caption={step3Rr[1].caption} />
            <ImageCaption src="/vm/synology/rr/rr_2_3_3.png" alt={step3Rr[2].alt} caption={step3Rr[2].caption} />
          </div>
        )}
        {activeLoader === "tinycore" && (
          <div className="flex flex-col space-y-10">
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_3_1.png" alt={step3Tc[0].alt} caption={step3Tc[0].caption} />
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_3_2.png" alt={step3Tc[1].alt} caption={step3Tc[1].caption} />
          </div>
        )}
      </StepSection>

      <StepSection n={4} title={t("step4.title")} stepLabel={t("stepBadge")}>
        <p className="mb-4 text-gray-800 leading-relaxed">{t("step4.intro")}</p>
        {activeLoader === "arc" && (
          <div className="flex flex-col space-y-10">
            <p className="text-gray-800 leading-relaxed">{t.rich("step4.arc.autoRich", { strong })}</p>
            <ImageCaption src="/vm/synology/arc/arc_1_4_1.png" alt={t("step4.arc.autoAlt")} caption={t("step4.arc.autoCaption")} />
            <p className="text-gray-800 leading-relaxed">{t("step4.arc.manualRich")}</p>
            <ImageCaption src="/vm/synology/arc/arc_1_4_2.png" alt={t("step4.arc.manualAlt")} caption={t("step4.arc.manualCaption")} />
            <ImageCaption src="/vm/synology/arc/arc_1_4_3.png" alt={t("step4.arc.snMacAlt")} caption={t("step4.arc.snMacCaption")} />
            <ImageCaption src="/vm/synology/arc/arc_1_4_4.png" alt={t("step4.arc.portmapAlt")} caption={t("step4.arc.portmapCaption")} />
            <ImageCaption src="/vm/synology/arc/arc_1_4_5.png" alt={t("step4.arc.addonsAlt")} caption={t("step4.arc.addonsCaption")} />
          </div>
        )}
        {activeLoader === "rr" && (
          <div className="flex flex-col space-y-10">
            <ImageCaption src="/vm/synology/rr/rr_2_4_1.png" alt={step4Rr[0].alt} caption={step4Rr[0].caption} />
            <ImageCaption src="/vm/synology/rr/rr_2_4_2.png" alt={step4Rr[1].alt} caption={step4Rr[1].caption} />
            <ImageCaption src="/vm/synology/rr/rr_2_4_3.png" alt={step4Rr[2].alt} caption={step4Rr[2].caption} />
          </div>
        )}
        {activeLoader === "tinycore" && (
          <div className="flex flex-col space-y-10">
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_4_1.png" alt={step4Tc[0].alt} caption={step4Tc[0].caption} />
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_4_2.png" alt={step4Tc[1].alt} caption={step4Tc[1].caption} />
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_4_3.png" alt={step4Tc[2].alt} caption={step4Tc[2].caption} />
            <ImageCaption src="/vm/synology/tinycore/tinycore_3_4_4.png" alt={step4Tc[3].alt} caption={step4Tc[3].caption} />
          </div>
        )}
      </StepSection>

      <StepSection n={5} title={t("step5.title")} stepLabel={t("stepBadge")}>
        <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("step5.introRich", { strong })}</p>
        {activeLoader === "arc" && (
          <ImageCaption src="/vm/synology/arc/arc_1_5_1.png" alt={t("step5.arc.alt")} caption={t("step5.arc.caption")} />
        )}
        {activeLoader === "rr" && (
          <ImageCaption src="/vm/synology/rr/rr_2_5_1.png" alt={t("step5.rr.alt")} caption={t("step5.rr.caption")} />
        )}
        {activeLoader === "tinycore" && (
          <ImageCaption src="/vm/synology/tinycore/tinycore_3_5_1.png" alt={t("step5.tinycore.alt")} caption={t("step5.tinycore.caption")} />
        )}
      </StepSection>

      <StepSection n={6} title={t("step6.title")} stepLabel={t("stepBadge")}>
        <p className="mb-4 text-gray-800 leading-relaxed">{t("step6.intro")}</p>
        {activeLoader === "arc" && (
          <ImageCaption src="/vm/synology/arc/arc_1_6_1.png" alt={t("step6.arc.alt")} caption={t("step6.arc.caption")} />
        )}
        {activeLoader === "rr" && (
          <ImageCaption src="/vm/synology/rr/rr_2_6_1.png" alt={t("step6.rr.alt")} caption={t("step6.rr.caption")} />
        )}
        {activeLoader === "tinycore" && (
          <ImageCaption src="/vm/synology/tinycore/tinycore_3_6_1.png" alt={t("step6.tinycore.alt")} caption={t("step6.tinycore.caption")} />
        )}
      </StepSection>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("dsmInstall.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("dsmInstall.intro")}</p>
      <pre className="bg-gray-100 p-3 rounded-md overflow-x-auto text-sm font-mono mb-4">
        <code>https://finds.synology.com</code>
      </pre>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("dsmInstall.afterCode")}</p>
      <div className="flex flex-col space-y-10">
        <ImageCaption src="/vm/synology/install_DSM.png" alt={t("dsmInstall.setupAlt")} caption={t("dsmInstall.setupCaption")} />
        <p className="text-gray-800 leading-relaxed">{t("dsmInstall.patience")}</p>
        <ImageCaption src="/vm/synology/finish_install_DSM.png" alt={t("dsmInstall.finishAlt")} caption={t("dsmInstall.finishCaption")} />
      </div>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("tips.heading")}</h2>

      <Callout variant="tip" title={t("tips.recentTitle")}>
        {t("tips.recentBody")}
      </Callout>

      <Callout variant="info" title={t("tips.updateTitle")}>
        {t("tips.updateBody")}
      </Callout>

      <Callout variant="warning" title={t("tips.warnTitle")}>
        {t("tips.warnBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-8 mb-3 text-gray-900">{t("tips.docsHeading")}</h3>
      <div className="flex flex-wrap gap-2">
        {docLinks.map((dl) => (
          <a
            key={dl.url}
            href={dl.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors"
          >
            <Github className="h-4 w-4 mr-2" />
            {dl.label}
          </a>
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ImageCaption({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
      <div className="w-full overflow-hidden rounded-md border border-gray-200">
        <Image
          src={src}
          alt={alt}
          width={768}
          height={0}
          style={{ height: "auto" }}
          className="w-full object-contain"
          sizes="(max-width: 768px) 100vw, 768px"
        />
      </div>
      <span className="mt-2 text-sm text-gray-600">{caption}</span>
    </div>
  )
}

function StepSection({ n, title, stepLabel, children }: { n: number; title: string; stepLabel: string; children: React.ReactNode }) {
  return (
    <section className="mt-10 border-b border-gray-200 pb-8">
      <div className="flex items-center gap-3 mb-4">
        <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
          {stepLabel} {n}
        </span>
        <h3 className="text-xl font-semibold text-gray-900 m-0">{title}</h3>
      </div>
      {children}
    </section>
  )
}
