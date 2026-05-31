"use client"

import Image from "next/image"
import {
  Wrench,
  Target,
  CheckCircle,
  Github,
  Server,
  HardDrive,
  Download,
  Settings,
  Cpu,
  Zap,
  Sliders,
  ExternalLink,
} from "lucide-react"
import { useState } from "react"
import { useTranslations, useMessages } from "next-intl"

type LoaderKey = "arc" | "rr" | "tinycore"

type StepMedia = { htmlBefore?: string; src: string; alt: string; caption: string }
type Step = {
  id: string
  title: string
  intro: string
  outro?: string
  loaders: Record<LoaderKey, StepMedia[]>
}
type LoaderLink = { name: string; url: string }
type ConfigRow = { param: string; value?: string; options?: string }
type DocLink = { label: string; url: string }

function ImageWithCaption({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <div className="flex flex-col items-center w-full max-w-[768px] mx-auto my-4">
      <div className="w-full rounded-md overflow-hidden">
        <Image
          src={src || "/placeholder.svg"}
          alt={alt}
          width={768}
          height={0}
          style={{ height: "auto" }}
          className="object-contain w-full"
          sizes="(max-width: 768px) 100vw, 768px"
        />
      </div>
      <span className="mt-2 text-sm text-gray-600">{caption}</span>
    </div>
  )
}

function StepNumber({ number }: { number: number }) {
  return (
    <div
      className="inline-flex items-center justify-center w-8 h-8 mr-3 text-white bg-blue-500 rounded-full"
      aria-hidden="true"
    >
      <span className="text-sm font-bold">{number}</span>
    </div>
  )
}

export default function Page() {
  const [activeLoader, setActiveLoader] = useState<LoaderKey>("arc")
  const t = useTranslations("docs.createVm.synology")

  const messages = useMessages() as unknown as {
    docs: { createVm: { synology: {
      intro: { loaders: LoaderLink[]; simplifies: string[] }
      config: { defaultRows: ConfigRow[]; advancedRows: ConfigRow[] }
      diskSelection: { virtualItems: string[]; physicalItems: string[] }
      vmCreation: { items: string[] }
      steps: Step[]
      tips: { docLinks: DocLink[] }
    } } }
  }
  const introLoaders = messages.docs.createVm.synology.intro.loaders
  const simplifies = messages.docs.createVm.synology.intro.simplifies
  const defaultRows = messages.docs.createVm.synology.config.defaultRows
  const advancedRows = messages.docs.createVm.synology.config.advancedRows
  const virtualItems = messages.docs.createVm.synology.diskSelection.virtualItems
  const physicalItems = messages.docs.createVm.synology.diskSelection.physicalItems
  const vmCreationItems = messages.docs.createVm.synology.vmCreation.items
  const steps = messages.docs.createVm.synology.steps
  const docLinks = messages.docs.createVm.synology.tips.docLinks

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-6">{t("title")}</h1>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4 flex items-center">
          <Server className="h-6 w-6 mr-2 text-blue-500" />
          {t("intro.heading")}
        </h2>
        <p className="mb-4">{t("intro.intro")}</p>
        <ul className="list-disc pl-5 mb-4">
          {introLoaders.map((l) => (
            <li key={l.name}>
              <a
                href={l.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline inline-flex items-center gap-1"
              >
                {l.name}
                <ExternalLink className="w-3 h-3" />
              </a>{" "}
            </li>
          ))}
          <li>{t("intro.customLoader")}</li>
        </ul>

        <p className="mb-4">{t("intro.simplifiesIntro")}</p>
        <ul className="list-disc pl-5 mb-4">
          {simplifies.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Settings className="h-5 w-5 mr-2 text-blue-500" />
            {t("config.heading")}
          </h3>
          <p className="mb-3">{t("config.intro")}</p>

          <h4 className="text-lg font-medium mt-12 mb-2 flex items-center">
            <Zap className="h-5 w-5 mr-2 text-green-500" />
            {t("config.defaultHeading")}
          </h4>
          <p className="mb-3">{t("config.defaultIntro")}</p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">{t("config.headerParam")}</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">{t("config.headerValue")}</th>
                </tr>
              </thead>
              <tbody>
                {defaultRows.map((row) => (
                  <tr key={row.param}>
                    <td className="py-2 px-4 border-b border-gray-200">{row.param}</td>
                    <td className="py-2 px-4 border-b border-gray-200">{row.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mb-4">{t("config.defaultOutro")}</p>

          <h4 className="text-lg font-medium mt-12 mb-2 flex items-center">
            <Sliders className="h-5 w-5 mr-2 text-orange-500" />
            {t("config.advancedHeading")}
          </h4>
          <p className="mb-3">{t("config.advancedIntro")}</p>

          <div className="overflow-x-auto mb-4">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">{t("config.headerParam")}</th>
                  <th className="py-2 px-4 border-b border-gray-200 bg-gray-50 text-left">{t("config.headerOptions")}</th>
                </tr>
              </thead>
              <tbody>
                {advancedRows.map((row) => (
                  <tr key={row.param}>
                    <td className="py-2 px-4 border-b border-gray-200">{row.param}</td>
                    <td className="py-2 px-4 border-b border-gray-200">{row.options}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <HardDrive className="h-5 w-5 mr-2 text-blue-500" />
            {t("diskSelection.heading")}
          </h3>
          <p className="mb-3">{t("diskSelection.intro")}</p>

          <h4 className="text-lg font-medium mt-4 mb-2">{t("diskSelection.virtualHeading")}</h4>
          <ul className="list-disc pl-5 mb-4">
            {virtualItems.map((_, idx) => (
              <li key={idx}>{t.rich(`diskSelection.virtualItems.${idx}`, { strong })}</li>
            ))}
          </ul>

          <h4 className="text-lg font-medium mt-4 mb-2">{t("diskSelection.physicalHeading")}</h4>
          <ul className="list-disc pl-5 mb-4">
            {physicalItems.map((_, idx) => (
              <li key={idx}>{t.rich(`diskSelection.physicalItems.${idx}`, { strong })}</li>
            ))}
          </ul>
        </div>

        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Download className="h-5 w-5 mr-2 text-blue-500" />
            {t("loaderInstall.heading")}
          </h3>
          <p className="mb-3">{t("loaderInstall.intro1")}</p>
          <p className="mb-4">
            {t.rich("loaderInstall.intro2Rich", { strong })}
          </p>
          <p className="mb-4">
            {t.rich("loaderInstall.customRich", { strong, code })}
          </p>
          <p className="mt-12 mb-4"></p>
          <p>{t("loaderInstall.uploadIntro")}</p>

          <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/vm/synology/add_loader.png"
            alt={t("loaderInstall.imageAlt")}
            caption={t("loaderInstall.imageCaption")}
          />
        </div>

        <div className="mt-16">
          <h3 className="text-xl font-semibold mb-3 flex items-center">
            <Cpu className="h-5 w-5 mr-2 text-blue-500" />
            {t("vmCreation.heading")}
          </h3>
          <p className="mb-3">{t("vmCreation.intro")}</p>
          <ul className="list-disc pl-5 mb-4">
            {vmCreationItems.map((_, idx) => (
              <li key={idx}>{t.rich(`vmCreation.items.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold mt-24 mb-4 flex items-center">
          <Wrench className="h-6 w-6 mr-2 text-blue-500" />
          {t("stepGuide.heading")}
        </h2>
        <p className="mb-4">{t("stepGuide.intro")}</p>

        <div className="bg-blue-50 p-4 rounded-lg mb-6">
          <h3 className="text-lg font-semibold mb-2">{t("stepGuide.selectorHeading")}</h3>
          <div className="flex space-x-4">
            {(["arc", "rr", "tinycore"] as LoaderKey[]).map((key) => (
              <button
                key={key}
                onClick={() => setActiveLoader(key)}
                className={`px-4 py-2 rounded-md font-medium ${
                  activeLoader === key
                    ? "bg-blue-500 text-white"
                    : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
                }`}
              >
                {t(`stepGuide.loaderButtons.${key}`)}
              </button>
            ))}
          </div>
        </div>
      </section>

      {steps.map((step, stepIdx) => {
        const media = step.loaders[activeLoader] || []
        return (
          <section key={step.id} className="mb-12 border-b pb-8">
            <h2 className="text-xl font-semibold mb-4 flex items-center" id={step.id}>
              <StepNumber number={stepIdx + 1} />
              {step.title}
            </h2>
            <p className="mb-4">{step.intro}</p>

            <div className="mt-6">
              <div className="flex flex-col space-y-8">
                {media.map((m, idx) => (
                  <div key={idx}>
                    {m.htmlBefore && (
                      <p className="mt-16 mb-2">
                        {t.rich(`steps.${stepIdx}.loaders.${activeLoader}.${idx}.htmlBefore`, { strong, code })}
                      </p>
                    )}
                    <ImageWithCaption src={m.src} alt={m.alt} caption={m.caption} />
                  </div>
                ))}
              </div>
            </div>

            {step.outro && <p className="mt-4">{step.outro}</p>}
          </section>
        )
      })}

      <section className="mb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center">
          <CheckCircle className="h-6 w-6 mr-3 text-green-500" />
          {t("dsmInstall.heading")}
        </h2>
        <p className="mb-4">{t("dsmInstall.intro")}</p>
        <div className="bg-gray-100 p-4 rounded-md overflow-x-auto text-sm mb-4">
          <code>https://finds.synology.com</code>
        </div>
        <p className="mb-6">{t("dsmInstall.afterCode")}</p>
        <div className="flex flex-col space-y-8">
          <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/vm/synology/install_DSM.png"
            alt={t("dsmInstall.setupAlt")}
            caption={t("dsmInstall.setupCaption")}
          />
          <p className="mt-8 mb-8">{t("dsmInstall.patience")}</p>
          <ImageWithCaption
            src="https://macrimi.github.io/ProxMenux/vm/synology/finish_install_DSM.png"
            alt={t("dsmInstall.finishAlt")}
            caption={t("dsmInstall.finishCaption")}
          />
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold mt-20 mb-4 flex items-center">
          <Target className="h-6 w-6 mr-2 text-blue-500" />
          {t("tips.heading")}
        </h2>
        <ul className="list-disc pl-5 space-y-4">
          <li>{t("tips.introItem")}</li>

          <div className="flex flex-wrap gap-4 mt-2">
            {docLinks.map((dl) => (
              <a
                key={dl.url}
                href={dl.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors"
              >
                <Github className="h-5 w-5 mr-2" />
                {dl.label}
              </a>
            ))}
          </div>

          <li>{t("tips.olderModels")}</li>

          <div className="bg-blue-100 border-l-4 border-blue-500 text-blue-700 p-4 mb-4">
            <p className="font-semibold">{t("tips.updateLabel")}</p>
            <p>{t("tips.updateBody")}</p>
          </div>

          <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mb-4">
            <p className="font-semibold">{t("tips.importantLabel")}</p>
            <p>{t("tips.importantBody")}</p>
          </div>
        </ul>
      </section>
    </div>
  )
}
