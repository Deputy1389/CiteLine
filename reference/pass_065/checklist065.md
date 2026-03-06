# Pass 065 Checklist

## Objective
Improve richer-packet chronology semantics by reducing overuse of generic `inpatient_daily_note` when stronger encounter-phase evidence exists.

## Problem
Pass 064 proved chronology no longer collapses to one event, but many richer packets still type clinically distinct phases as `inpatient_daily_note`.

## Acceptance
- richer packets retain chronology row counts
- specific encounter types increase where evidence supports them
- no return of `1900-01-01` sentinel PT dates
- no junk front-page anchor regression
- terminal status remains sensible

## Validation Set
- `PacketIntake/05_minor_quick/packet.pdf`
- `PacketIntake/10_surgical_standard/packet.pdf`
- `PacketIntake/batch_029_complex_prior/packet.pdf`
