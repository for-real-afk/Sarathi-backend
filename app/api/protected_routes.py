from fastapi import APIRouter, Request

router = APIRouter(tags=["Protected Resources"])

@router.get("/admin/dashboard")
def admin_dashboard(request: Request):
    """
    Protected Admin Dashboard (Only accessible by ADMIN).
    """
    return {
        "status": "success",
        "message": "Welcome to the Admin Dashboard",
        "user_id": getattr(request.state, "user_id", None),
        "roles": getattr(request.state, "roles", [])
    }

@router.get("/volunteers/dashboard")
def volunteers_dashboard(request: Request):
    """
    Protected Volunteers Portal (Accessible by ADMIN, CENTRAL_HUB, LOCAL_HUB).
    """
    return {
        "status": "success",
        "message": "Welcome to the Volunteers Portal",
        "user_id": getattr(request.state, "user_id", None),
        "roles": getattr(request.state, "roles", [])
    }

@router.get("/citizens/dashboard")
def citizens_dashboard(request: Request):
    """
    Protected Citizens Portal (Accessible by ADMIN, CENTRAL_HUB, LOCAL_HUB, VOLUNTEER).
    """
    return {
        "status": "success",
        "message": "Welcome to the Citizens Portal",
        "user_id": getattr(request.state, "user_id", None),
        "roles": getattr(request.state, "roles", [])
    }

@router.get("/cases/dashboard")
def cases_dashboard(request: Request):
    """
    Protected Case Management Portal (Accessible by ADMIN, CENTRAL_HUB, LOCAL_HUB, VOLUNTEER, CITIZEN).
    """
    return {
        "status": "success",
        "message": "Welcome to the Cases Portal",
        "user_id": getattr(request.state, "user_id", None),
        "roles": getattr(request.state, "roles", [])
    }
