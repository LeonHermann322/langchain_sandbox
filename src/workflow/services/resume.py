from pdf2image import convert_from_path
import pytesseract

from ..core.settings import WorkflowSettings


class ResumeExtractor:
    def __init__(self, settings: WorkflowSettings | None = None):
        self.settings = settings or WorkflowSettings.from_env()
        pytesseract.pytesseract.tesseract_cmd = self.settings.tesseract_cmd

    def extract(self, file_path: str, job_location: str) -> str:
        resume_text = ""
        try:
            pages = convert_from_path(
                file_path,
                dpi=300,
                poppler_path=self.settings.poppler_path,
            )
            for page_image in pages:
                resume_text += (
                    pytesseract.image_to_string(page_image, lang="eng") + "\n"
                )
        except Exception:
            return f"Junior AI Engineer in {job_location}"

        resume_text = resume_text.strip()
        if not resume_text or len(resume_text) < 100:
            return f"Junior AI Engineer in {job_location}"

        print(f"✅ OCR Completed ({len(resume_text)} chars)")
        return (
            f"Junior AI roles in {job_location} for a candidate with these skills: "
            f"{resume_text[:1000]}"
        )
