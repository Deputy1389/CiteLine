import random
from typing import Dict
from .schema import Archetype, DocumentType

def allocate_pages(archetype: Archetype, target_pages: int, noise_level: str, rnd: random.Random) -> Dict[str, int]:
    """
    Allocates pages to different document types to hit a hard target_pages count.
    Returns a dictionary of {doc_type_key: page_count}.
    """
    
    # 1. Define Minimums
    mins = {
        "prior_records": 4 if archetype != Archetype.COMPLEX_PRIOR else 8,
        "ed_visit": 18,
        "xr_c": 2,
        "xr_l": 2,
        "mri_c": 6 if archetype in [Archetype.HERNIATION, Archetype.SURGICAL, Archetype.COMPLEX_PRIOR] else 0,
        "pcp_visit": 6,
        "pt_eval": 6,
        "pt_daily": 60 if target_pages < 250 else 120,
        "pt_progress": 6 if archetype != Archetype.MINOR else 0,
        "pt_discharge": 2,
        "ortho_consult": 18 if archetype != Archetype.MINOR else 0,
        "procedure_esi": 6 if archetype in [Archetype.HERNIATION, Archetype.SURGICAL] else 0,
        "billing": 30 if target_pages < 250 else 80,
        "noise": 0
    }

    # 2. Adjust for Noise
    if noise_level in ["mixed", "heavy"]:
        # Allocate 5-12% to noise
        noise_pages = int(target_pages * rnd.uniform(0.05, 0.12))
        mins["noise"] = noise_pages
    elif noise_level == "light":
        mins["noise"] = int(target_pages * 0.02)
        
    # 3. Calculate Remainder
    total_min = sum(mins.values())
    
    if total_min > target_pages:
        # Aggressive Compression
        # 1. Reduce bulk items to near-zero first
        keys_to_reduce = ["pt_daily", "billing"]
        for k in keys_to_reduce:
             if mins[k] > 2:
                  reduction = mins[k] - 2
                  if total_min - reduction < target_pages:
                       # reduce just enough
                       needed = total_min - target_pages
                       mins[k] -= needed
                       total_min -= needed
                  else:
                       mins[k] = 2
                       total_min -= reduction
                       
        # 2. If still over, scale everything proportionally
        if total_min > target_pages:
            scale_factor = target_pages / total_min
            for k in mins:
                if mins[k] > 0:
                    mins[k] = max(1, int(mins[k] * scale_factor))
            
            # Recalculate
            total_min = sum(mins.values())
            
        # 3. Final trim/pad to match exactly
        while total_min > target_pages:
            # Trim from largest
            largest_key = max(mins, key=mins.get)
            if mins[largest_key] > 0:
                mins[largest_key] -= 1
                total_min -= 1
            else:
                break # Should not happen unless target=0
                
        while total_min < target_pages:
            # Pad largest (unlikely but possible due to floor)
            largest_key = max(mins, key=mins.get)
            mins[largest_key] += 1
            total_min += 1

    remainder = target_pages - sum(mins.values())
    
    # 4. Distribute Remainder (Weighted)
    if remainder > 0:
        weights = {
            "pt_daily": 50,
            "billing": 30,
            "ed_visit": 5,
            "ortho_consult": 5,
            "mri_c": 2,
            "noise": 5 if noise_level != "none" else 0
        }
        
        # Normalize weights to active keys
        active_keys = [k for k, v in mins.items() if v > 0 and k in weights]
        total_weight = sum(weights[k] for k in active_keys)
        
        if total_weight > 0:
            for k in active_keys:
                w = weights[k]
                share = int(remainder * (w / total_weight))
                mins[k] += share
        else:
             # Fallback if no weighted keys active (unlikely)
             mins["pt_daily"] += remainder

        # Fix rounding error
        current_total = sum(mins.values())
        diff = target_pages - current_total
        if diff != 0:
            # Add to biggest bucket
            mins["pt_daily"] += diff
            
    return mins
