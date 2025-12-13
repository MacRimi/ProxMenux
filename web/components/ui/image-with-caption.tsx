"use client"

import Image from "next/image"

interface ImageWithCaptionProps {
  src: string
  alt: string
  caption: string
  width?: number
  height?: number
}

export function ImageWithCaption({ src, alt, caption, width = 800, height = 450 }: ImageWithCaptionProps) {
  return (
    <figure className="my-4">
      <Image
        src={src || "/placeholder.svg"}
        alt={alt}
        width={width}
        height={height}
        className="rounded-lg shadow-md w-full"
      />
      <figcaption className="text-center text-sm text-gray-600 mt-2">{caption}</figcaption>
    </figure>
  )
}
