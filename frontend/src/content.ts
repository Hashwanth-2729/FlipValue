import type { EvidenceStatus, Grade, Region, RepairType } from "./types";

export const REGIONS: { value: Region; label: string; currency: "INR" | "USD" }[] = [
  { value: "IN", label: "India (INR)", currency: "INR" },
  { value: "US", label: "United States (USD)", currency: "USD" },
];

export const GRADE_LABEL: Record<Grade, string> = {
  excellent: "Excellent",
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  faulty: "Faulty",
};

export const GRADE_HELP: Record<Grade, string> = {
  excellent: "Like new, fully working",
  good: "Light wear, fully working",
  fair: "Visible scratches or dents, fully working",
  poor: "Heavy wear or cracked glass, still working",
  faulty: "At least one function does not work properly",
};

export const FAULT_LABEL: Record<string, string> = {
  software_instability: "Software instability",
  storage_pressure: "Storage nearly full",
  battery_wear: "Battery wear",
  charging_path: "Charging problem",
  display_damage: "Display or touch problem",
  camera_fault: "Camera problem",
  audio_fault: "Speaker or microphone problem",
  connectivity_issue: "Connectivity problem",
  liquid_damage: "Liquid damage",
};

export const REPAIR_LABEL: Record<RepairType, string> = {
  battery_replacement: "Battery replacement",
  charging_port_replacement: "Charging port replacement",
  screen_replacement: "Screen replacement",
  camera_module_replacement: "Camera module replacement",
  audio_component_replacement: "Speaker / microphone replacement",
  liquid_damage_service: "Liquid damage service",
  software_reset: "Software reset",
};

/** Repairs that address a reported fault, offered as suggestions only. */
export const REPAIR_FOR_FAULT: Record<string, RepairType> = {
  battery_wear: "battery_replacement",
  charging_path: "charging_port_replacement",
  display_damage: "screen_replacement",
  camera_fault: "camera_module_replacement",
  audio_fault: "audio_component_replacement",
  liquid_damage: "liquid_damage_service",
};

export const EVIDENCE: Record<EvidenceStatus, { label: string; tone: "good" | "warn" | "mock" | "none"; help: string }> = {
  evidence_backed: {
    label: "Evidence-backed",
    tone: "good",
    help: "At least one condition has 10+ recent completed sales.",
  },
  limited: { label: "Limited evidence", tone: "warn", help: "Some recent prices, but few, older or asking prices." },
  estimated: {
    label: "FlipValue estimate",
    tone: "warn",
    help: "No sales data yet; values are modelled from approximate current price ranges.",
  },
  mock_only: { label: "Mock data only", tone: "mock", help: "Only synthetic development data. Not real prices." },
  insufficient: {
    label: "Not enough evidence",
    tone: "none",
    help: "Known model, but not enough recent prices to give an estimate.",
  },
};

export const QUALITY_LABEL = {
  evidence_backed: "Evidence-backed",
  limited: "Limited evidence",
  modelled: "FlipValue estimate",
} as const;

export const RANGE_HELP = {
  p10_p90: "Middle 80% of prices (10th–90th percentile)",
  min_max: "Lowest to highest price (too few observations for percentiles)",
} as const;
