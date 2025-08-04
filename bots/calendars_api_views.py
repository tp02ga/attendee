from drf_spectacular.openapi import OpenApiResponse
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import ApiKeyAuthentication
from .calendars_api_utils import create_calendar
from .serializers import CalendarSerializer, CreateCalendarSerializer

TokenHeaderParameter = [
    OpenApiParameter(
        name="Authorization",
        type=str,
        location=OpenApiParameter.HEADER,
        description="API key for authentication",
        required=True,
        default="Token YOUR_API_KEY_HERE",
    ),
    OpenApiParameter(
        name="Content-Type",
        type=str,
        location=OpenApiParameter.HEADER,
        description="Should always be application/json",
        required=True,
        default="application/json",
    ),
]

NewlyCreatedCalendarExample = OpenApiExample(
    "Newly Created Calendar",
    value={
        "id": "cal_abcdef1234567890",
        "platform": "google",
        "state": "connected",
        "metadata": {"department": "engineering", "team": "backend"},
        "deduplication_key": "engineering-main-calendar",
        "connection_failure_data": None,
        "created_at": "2025-01-13T10:30:00.123456Z",
        "updated_at": "2025-01-13T10:30:00.123456Z",
    },
    description="Example response when a calendar is successfully created",
)


class CalendarCreateView(APIView):
    authentication_classes = [ApiKeyAuthentication]

    @extend_schema(
        operation_id="Create Calendar",
        summary="Create a new calendar",
        description="After being created, the calendar will be connected to the specified calendar platform.",
        request=CreateCalendarSerializer,
        responses={
            201: OpenApiResponse(
                response=CalendarSerializer,
                description="Calendar created successfully",
                examples=[NewlyCreatedCalendarExample],
            ),
            400: OpenApiResponse(description="Invalid input"),
        },
        parameters=TokenHeaderParameter,
        tags=["Calendars"],
    )
    def post(self, request):
        calendar, error = create_calendar(data=request.data, project=request.auth.project)
        if error:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        return Response(CalendarSerializer(calendar).data, status=status.HTTP_201_CREATED)
