import logging
from sqlalchemy.orm import Session
from app.models import Survey, CitizenProfile, HouseholdProfile, CitizenTimeline, VolunteerProfile, WelfareCase, User

logger = logging.getLogger("uvicorn.error")


def sync_survey_to_crm(db: Session, survey: Survey) -> CitizenProfile:
    """
    Synchronizes a submitted Survey to the Citizen Registry CRM.
    Checks if a citizen already exists by matching name and mobile number.
    If match found, updates demographic and household data.
    If no match, creates a new Citizen and Household profile.
    Automatically logs Timeline Events.
    """
    data = survey.data or {}
    
    # 1. Map name
    first = data.get("firstName") or survey.first_name or ""
    last = data.get("lastName") or survey.last_name or ""
    full_name = f"{first} {last}".strip()
    if not full_name:
        full_name = "Anonymous Beneficiary"

    phone = data.get("primaryMobile") or survey.primary_mobile or ""
    
    # Map age
    age_val = None
    age_str = data.get("age")
    if age_str:
        try:
            age_val = int(float(age_str))
        except ValueError:
            pass

    # Map Aadhaar Reference (Mask for privacy)
    aadhaar = data.get("aadhaarNumber")
    aadhaar_ref = "Not Provided"
    if aadhaar:
        clean_aadhaar = str(aadhaar).replace(" ", "").replace("-", "")
        if len(clean_aadhaar) >= 4:
            aadhaar_ref = f"XXXX-XXXX-{clean_aadhaar[-4:]}"
        else:
            aadhaar_ref = "Provided (Consent Active)"
            
    # Address composition
    house = data.get("houseNo") or ""
    street = data.get("street") or ""
    address = f"{house}, {street}".strip(", ") or "Not Specified"

    # Poverty Classification logic
    annual_income = data.get("annualIncome") or "0"
    poverty_class = "APL" # Above Poverty Line default
    try:
        # Check if annual income is represented as integer/float
        inc_val = int(float(str(annual_income).replace(",", "").replace("₹", "").strip()))
        if inc_val <= 120000:
            poverty_class = "BPL" # Below Poverty Line
    except ValueError:
        # Fallback parsing for string ranges (e.g. "< 1,00,000", "Below 1 Lakh")
        lower_inc_indicators = ["<", "below", "0-", "less than", "50,000"]
        if any(ind in str(annual_income).lower() for ind in lower_inc_indicators):
            poverty_class = "BPL"

    # Housing Status composition
    ht = data.get("housingType") or "Kutcha"
    ho = data.get("housingOwnership") or "Rented"
    housing_status = f"{ht} ({ho})"

    # Family members mapping
    raw_members = data.get("familyMembers") or []
    family_members = []
    for m in raw_members:
        family_members.append({
            "name": m.get("name", "Unknown"),
            "relationship": m.get("relation", "Other"),
            "age": m.get("age", "0"),
            "gender": m.get("gender", "--"),
            "education": m.get("education", ""),
            "occupation": m.get("employment", ""),
            "disability": m.get("disability", "No"),
            "illness": m.get("illness", "")
        })

    # Find existing citizen profile
    db_citizen = db.query(CitizenProfile).filter(
        CitizenProfile.name.ilike(full_name),
        CitizenProfile.phone == phone
    ).first()

    try:
        if db_citizen:
            logger.info(f"Sync: Found existing citizen ID {db_citizen.id}. Updating details...")
            # Update citizen details
            db_citizen.aadhaar_reference = aadhaar_ref
            db_citizen.gender = data.get("gender") or db_citizen.gender
            db_citizen.age = age_val or db_citizen.age
            db_citizen.address = address
            db_citizen.state = data.get("state") or db_citizen.state
            db_citizen.district = data.get("district") or db_citizen.district
            db_citizen.mandal = data.get("mandal") or db_citizen.mandal
            db_citizen.village = data.get("village") or db_citizen.village

            # Update or create household
            db_hh = None
            if db_citizen.household_id:
                db_hh = db.query(HouseholdProfile).filter(HouseholdProfile.id == db_citizen.household_id).first()
            
            if db_hh:
                db_hh.income = data.get("annualIncome") or data.get("monthlyIncomeRange")
                db_hh.housing_status = housing_status
                db_hh.land_ownership = data.get("agriLand")
                db_hh.occupation = data.get("mainOccupation")
                db_hh.poverty_classification = poverty_class
                db_hh.family_members = family_members
            else:
                db_hh = HouseholdProfile(
                    income=data.get("annualIncome") or data.get("monthlyIncomeRange"),
                    housing_status=housing_status,
                    land_ownership=data.get("agriLand"),
                    occupation=data.get("mainOccupation"),
                    poverty_classification=poverty_class,
                    family_members=family_members
                )
                db.add(db_hh)
                db.commit()
                db.refresh(db_hh)
                db_citizen.household_id = db_hh.id

            db.commit()

            # Log updating timeline events
            e_update = CitizenTimeline(
                citizen_id=db_citizen.id,
                event_type="Volunteer Visit",
                description="Welfare survey re-submitted/updated by surveyor."
            )
            db.add(e_update)
            
            # Check eligibility count if saved in data
            schemes_count = len(data.get("applicableSchemes", [])) or len(data.get("currentSchemes", []))
            e_elig = CitizenTimeline(
                citizen_id=db_citizen.id,
                event_type="Eligibility Runs",
                description=f"Welfare intelligence pipeline evaluated {schemes_count} eligible schemes."
            )
            db.add(e_elig)
            db.commit()

        else:
            logger.info("Sync: No existing citizen profile. Creating new registry...")
            
            # Create Household first
            db_hh = HouseholdProfile(
                income=data.get("annualIncome") or data.get("monthlyIncomeRange"),
                housing_status=housing_status,
                land_ownership=data.get("agriLand"),
                occupation=data.get("mainOccupation"),
                poverty_classification=poverty_class,
                family_members=family_members
            )
            db.add(db_hh)
            db.commit()
            db.refresh(db_hh)

            # Create Citizen
            db_citizen = CitizenProfile(
                name=full_name,
                phone=phone,
                aadhaar_reference=aadhaar_ref,
                gender=data.get("gender"),
                age=age_val,
                address=address,
                state=data.get("state"),
                district=data.get("district"),
                mandal=data.get("mandal"),
                village=data.get("village"),
                household_id=db_hh.id
            )
            db.add(db_citizen)
            db.commit()
            db.refresh(db_citizen)

            # Log profile creation timeline event
            e_create = CitizenTimeline(
                citizen_id=db_citizen.id,
                event_type="Profile Creation",
                description="Citizen registry created via Welfare Survey submission."
            )
            db.add(e_create)

            # Log eligibility check event
            schemes_count = len(data.get("applicableSchemes", []))
            e_elig = CitizenTimeline(
                citizen_id=db_citizen.id,
                event_type="Eligibility Runs",
                description=f"Welfare rules evaluated. Discovered potential eligibility for schemes."
            )
            db.add(e_elig)
            db.commit()
            
            logger.info(f"Sync: Successfully created Citizen Profile ID {db_citizen.id} and Household Profile ID {db_hh.id}.")

        # 4. Trigger Automatic Case Assignment Engine if eligible for any schemes
        applicable_schemes = data.get("applicableSchemes", [])
        if applicable_schemes and db_citizen:
            active_case = db.query(WelfareCase).filter(
                WelfareCase.citizen_id == db_citizen.id,
                WelfareCase.status != "Resolved"
            ).first()
            
            if not active_case:
                matched_vol_id = None
                assigned_status = "Unassigned"
                
                if db_citizen.district:
                    candidates = db.query(VolunteerProfile).filter(
                        VolunteerProfile.district.ilike(db_citizen.district),
                        VolunteerProfile.availability == True
                    ).all()
                    
                    if candidates:
                        least_workload = None
                        selected_vol = None
                        for vol in candidates:
                            active_count = db.query(WelfareCase).filter(
                                WelfareCase.volunteer_id == vol.id,
                                WelfareCase.status != "Resolved"
                            ).count()
                            if least_workload is None or active_count < least_workload:
                                least_workload = active_count
                                selected_vol = vol
                        if selected_vol:
                            matched_vol_id = selected_vol.id
                            assigned_status = "Assigned"
                
                scheme_title = applicable_schemes[0]
                new_case = WelfareCase(
                    citizen_id=db_citizen.id,
                    volunteer_id=matched_vol_id,
                    title=f"Welfare Support: {scheme_title}",
                    description=f"Automated case registered for {db_citizen.name} who is eligible for {scheme_title}.",
                    status=assigned_status,
                    follow_up_tasks=[
                        {"task_name": "Verify Aadhaar Proof", "completed": False},
                        {"task_name": "Collect Income Certificate", "completed": False},
                        {"task_name": "Fill Scheme Application Form", "completed": False}
                    ]
                )
                db.add(new_case)
                db.commit()
                db.refresh(new_case)
                
                timeline_desc = f"Welfare Case created for '{scheme_title}'."
                if matched_vol_id:
                    vol_user = db.query(User).join(VolunteerProfile).filter(VolunteerProfile.id == matched_vol_id).first()
                    timeline_desc += f" Automatically assigned to volunteer '{vol_user.username}' (District: {db_citizen.district})."
                else:
                    timeline_desc += " Case remains unassigned (No available volunteers in the district)."
                    
                e_case = CitizenTimeline(
                    citizen_id=db_citizen.id,
                    event_type="Cases Created",
                    description=timeline_desc
                )
                db.add(e_case)
                db.commit()

        return db_citizen

    except Exception as e:
        logger.error(f"Sync: Error occurred while syncing survey to CRM: {str(e)}")
        db.rollback()
        return None
