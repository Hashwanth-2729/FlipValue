"""Customer questionnaire -> contract grade + fault categories.

The mapping applies the grade definitions in the integration contract (§6); it is definitional, not a price
adjustment. Every answer is customer-reported: nothing here verifies hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

YesNo = Literal["yes", "no"]
Check = Literal["working", "issue", "not_tested"]


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    powers_on: YesNo
    usable_normally: Literal["yes", "no", "unsure"]
    screen: Literal["perfect", "light_scratches", "heavy_scratches", "cracked", "display_fault"]
    screen_touch_works: YesNo | None = None   # asked only when screen == "cracked"
    body: Literal["like_new", "light_wear", "visible_wear", "heavy_wear", "cracked_back"]
    battery: Literal["normal", "drains_fast", "swollen", "unknown"]
    charging: Literal["normal", "unreliable", "not_charging"]
    cameras: Check
    audio: Check
    buttons: Check
    connectivity: Check
    liquid_damage: Literal["no", "yes", "unsure"]
    previous_repairs: list[Literal["screen", "battery", "back_glass", "charging_port", "camera", "other"]] = []

    @model_validator(mode="after")
    def _touch_question(self) -> Assessment:
        if self.screen == "cracked" and self.screen_touch_works is None:
            raise ValueError("screen_touch_works is required when the screen is cracked")
        if self.screen != "cracked" and self.screen_touch_works is not None:
            raise ValueError("screen_touch_works is only asked when the screen is cracked")
        return self


@dataclass
class Derivation:
    grade: str
    faults: list[str]
    reasons: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    not_used: list[str] = field(default_factory=list)
    safety: list[str] = field(default_factory=list)


_COSMETIC_RANK = ["excellent", "good", "fair", "poor"]
_SCREEN = {"perfect": "excellent", "light_scratches": "good", "heavy_scratches": "fair", "cracked": "poor"}
_BODY = {"like_new": "excellent", "light_wear": "good", "visible_wear": "fair", "heavy_wear": "poor",
         "cracked_back": "poor"}


def derive(a: Assessment) -> Derivation:
    faults: list[str] = []
    functional: list[str] = []
    uncertain: list[str] = []
    safety: list[str] = []

    if a.powers_on == "no":
        functional.append("the phone does not power on")
    if a.usable_normally == "no":
        functional.append("it cannot be unlocked or used normally")
    elif a.usable_normally == "unsure":
        uncertain.append("You were unsure whether the phone can be unlocked and used normally; if it cannot, it "
                         "would be graded faulty.")
    if a.screen == "display_fault" or (a.screen == "cracked" and a.screen_touch_works == "no"):
        faults.append("display_damage")
        functional.append("the display or touch does not work properly")
    if a.battery in ("drains_fast", "swollen"):
        faults.append("battery_wear")
        functional.append("the battery drains fast" if a.battery == "drains_fast" else "the battery is swollen")
    if a.battery == "swollen":
        safety.append("A swollen battery can be a fire risk. Stop charging it and get it checked before selling.")
    if a.battery == "unknown":
        uncertain.append("Battery condition unknown.")
    if a.charging != "normal":
        faults.append("charging_path")
        functional.append("charging is unreliable" if a.charging == "unreliable" else "the phone does not charge")
    for answer, fault, label in ((a.cameras, "camera_fault", "cameras"), (a.audio, "audio_fault",
                                 "speakers/microphones"), (a.connectivity, "connectivity_issue",
                                 "connectivity (Wi-Fi, mobile, Bluetooth)")):
        if answer == "issue":
            faults.append(fault)
            functional.append(f"{label} have a problem")
        elif answer == "not_tested":
            uncertain.append(f"{label.capitalize()} not tested; if they do not work, the phone would be graded "
                             "faulty.")
    if a.buttons == "issue":
        functional.append("buttons have a problem")  # no contract fault category for buttons
    elif a.buttons == "not_tested":
        uncertain.append("Buttons not tested.")
    if a.liquid_damage == "yes":
        faults.append("liquid_damage")
    elif a.liquid_damage == "unsure":
        uncertain.append("Possible liquid exposure: buyers usually check for it and may offer less.")

    cosmetic = max(_SCREEN.get(a.screen, "excellent"), _BODY[a.body], key=_COSMETIC_RANK.index)
    reasons: list[str] = []
    if functional:
        grade = "faulty"
        reasons.append("Graded faulty because " + "; ".join(functional) + ".")
        reasons.append(f"Cosmetically it would otherwise be '{cosmetic}'.")
    else:
        grade = cosmetic
        reasons.append(f"Everything you reported works, so the grade follows the cosmetic condition: '{grade}'.")
    if "liquid_damage" in faults and grade != "faulty":
        reasons.append("Liquid damage is recorded as a fault but does not change the grade while everything works.")

    not_used = []
    if a.previous_repairs:
        not_used.append("Previous repairs are recorded in your summary but do not change the estimate "
                        "(no evidence yet for how buyers price them).")
    return Derivation(grade, faults, reasons, uncertain, not_used, safety)
