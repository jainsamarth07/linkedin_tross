from typing import List, Optional
from pydantic import BaseModel, Field


class Experience(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    employment_type: Optional[str] = None
    duration: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    company_logo_url: Optional[str] = None


class Education(BaseModel):
    school: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    duration: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    school_logo_url: Optional[str] = None


class Certification(BaseModel):
    name: Optional[str] = None
    issuing_organization: Optional[str] = None
    issue_date: Optional[str] = None
    credential_id: Optional[str] = None
    credential_url: Optional[str] = None


class Skill(BaseModel):
    name: str
    endorsement_count: Optional[int] = None


class Language(BaseModel):
    name: str
    proficiency: Optional[str] = None


class ProfileImages(BaseModel):
    profile_photo_url: Optional[str] = None
    background_photo_url: Optional[str] = None


class LinkedInProfile(BaseModel):
    profile_url: str
    name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    about: Optional[str] = None
    connections: Optional[str] = None
    followers: Optional[str] = None
    images: ProfileImages = Field(default_factory=ProfileImages)
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    skills: List[Skill] = Field(default_factory=list)
    certifications: List[Certification] = Field(default_factory=list)
    languages: List[Language] = Field(default_factory=list)
    scraped_at: str
    warnings: List[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
