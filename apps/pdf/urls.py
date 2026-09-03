from django.urls import path

from .views import (
    CompressPDFAPIView,
    MergePDFAPIView,
    PDFJobDetailAPIView,
    PDFJobDownloadAPIView,
    RemovePagesPDFAPIView,
    ReorderPDFAPIView,
    SplitPDFAPIView,
)

urlpatterns = [
    path("merge/", MergePDFAPIView.as_view(), name="pdf-merge"),
    path("split/", SplitPDFAPIView.as_view(), name="pdf-split"),
    path("compress/", CompressPDFAPIView.as_view(), name="pdf-compress"),
    path("reorder/", ReorderPDFAPIView.as_view(), name="pdf-reorder"),
    path("remove-pages/", RemovePagesPDFAPIView.as_view(), name="pdf-remove-pages"),
    path("jobs/<str:job_id>/", PDFJobDetailAPIView.as_view(), name="pdf-job-detail"),
    path("jobs/<str:job_id>/download/", PDFJobDownloadAPIView.as_view(), name="pdf-job-download"),
]
