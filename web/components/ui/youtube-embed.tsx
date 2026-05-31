import React from "react"
import { cn } from "@/lib/utils"

interface YouTubeEmbedProps {
  videoId: string
  title: string
  caption?: string
  className?: string
}

export const YouTubeEmbed: React.FC<YouTubeEmbedProps> = ({
  videoId,
  title,
  caption,
  className,
}) => {
  return (
    <div className={cn("my-6 not-prose", className)}>
      <div
        className="relative w-full overflow-hidden rounded-lg shadow-lg bg-black"
        style={{ paddingTop: "56.25%" }}
      >
        <iframe
          className="absolute inset-0 h-full w-full"
          src={`https://www.youtube-nocookie.com/embed/${videoId}`}
          title={title}
          loading="lazy"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          referrerPolicy="strict-origin-when-cross-origin"
          allowFullScreen
        />
      </div>
      {caption && (
        <p className="mt-2 text-xs text-gray-500 text-center">{caption}</p>
      )}
    </div>
  )
}
