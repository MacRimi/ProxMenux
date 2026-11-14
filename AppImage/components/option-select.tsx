"use client"

// One choice from a list, with the dropdown used across the Monitor.
import type React from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"

// The dropdown does not take an empty value, which some lists use for
// "any" or "none": it stands in for it.
const EMPTY = "__empty__"

export interface Option {
  value: string | number
  label: React.ReactNode
}

const toItem = (value: string | number) => (value === "" ? EMPTY : String(value))

export function OptionSelect({ value, onChange, options, className, ariaLabel, disabled }: {
  value: string | number | undefined
  onChange: (value: string) => void
  options: Option[]
  className?: string
  ariaLabel?: string
  disabled?: boolean
}) {
  return (
    <Select value={toItem(value ?? "")} disabled={disabled} onValueChange={v => onChange(v === EMPTY ? "" : v)}>
      <SelectTrigger aria-label={ariaLabel} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map(option => (
          <SelectItem key={toItem(option.value)} value={toItem(option.value)}>{option.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
