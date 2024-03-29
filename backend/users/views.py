from core.texts import (
    MAX_RESET_ATTEMPTS,
    USER_ERROR_DELETE_ACCOUNT,
    USER_SUCCESS_DELETE_ACCOUNT,
    USER_ERROR_DELETE,
)
from core.utils import (
    generate_reset_code,
    get_attempts_word,
    send_confirmation_code,
)
from django.db.transaction import atomic
from django.shortcuts import get_object_or_404

from djoser.permissions import CurrentUserOrAdminOrReadOnly
from djoser.views import TokenCreateView, TokenDestroyView
from djoser.views import UserViewSet as DjoserUserViewSet

from drf_spectacular.utils import (
    OpenApiExample,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .models import User, UserCoordinates
from .serializers import (
    CoordinatesUserSerializer,
    ResetCodeSerializer,
    SetUserPasswordSerializer,
    UserSerializer,
    UserTokenSerializer,
)


@extend_schema(tags=["Пользователи"])
@extend_schema_view(
    list=extend_schema(summary="Список пользователей"),
    retrieve=extend_schema(summary="Получение профиля одного пользователя"),
    create=extend_schema(summary="Создание пользователя"),
    update=extend_schema(summary="Полное обновление пользователя"),
    partial_update=extend_schema(summary="Частичное обновление пользователя"),
    destroy=extend_schema(summary="Удаление пользователя"),
    me=extend_schema(summary="Данные текущего пользователя"),
    reset_code=extend_schema(summary="Сброс пароля пользователя"),
    set_user_password=extend_schema(
        summary="Изменение пароля пользователя после сброса."
    ),
    set_user_coordinates=extend_schema(
        summary="Обновление координат пользователя."
    ),
)
class PublicUserViewSet(DjoserUserViewSet):
    """Представление для работы с публичными данными пользователей."""

    queryset = User.objects.all()
    serializer_class = UserSerializer
    pagination_class = PageNumberPagination
    permission_classes = [CurrentUserOrAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == "me":
            return UserSerializer
        if self.action == "reset_code":
            return ResetCodeSerializer
        if self.action == "set_user_password":
            return SetUserPasswordSerializer
        if self.action == "set_user_coordinates":
            return CoordinatesUserSerializer

        return super().get_serializer_class()

    def destroy(self, request, *args, **kwargs):
        """Удаление пользователя."""

        instance = self.get_object()

        try:
            with atomic():
                if instance != request.user:
                    return Response(
                        {"error": USER_ERROR_DELETE_ACCOUNT},
                        status=status.HTTP_403_FORBIDDEN,
                    )

                instance.delete()

                return Response(
                    {"detail": USER_SUCCESS_DELETE_ACCOUNT},
                    status=status.HTTP_200_OK,
                )
        except Exception as e:
            return Response(
                {"error": f"{USER_ERROR_DELETE}: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        description="Сброс пароля пользователя. Введите почту, "
        "чтобы получить код для сброса пароля.",
        responses={
            200: OpenApiExample(
                {"success": "Код успешно отправлен на почту"},
            )
        },
    )
    @action(
        detail=False,
        url_path="reset-code",
        permission_classes=[AllowAny],
        methods=["post"],
    )
    def reset_code(self, request):
        serializer = ResetCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise ValidationError(
                {"error": "Пользователь с указанной почтой не найден."}
            )

        code = generate_reset_code()

        user.password_reset_code = code
        user.password_reset_attempts = 0
        user.save()

        send_confirmation_code(user.email, code)

        return Response(
            {"success": "Код успешно отправлен на почту"},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        description="Изменение пароля пользователя после сброса. "
        "Введите почту, код и новый пароль.",
        responses={
            200: OpenApiExample(
                {"success": "Пароль успешно изменен."},
            )
        },
    )
    @action(
        detail=False,
        url_path="set-user-password",
        permission_classes=[AllowAny],
        methods=["post"],
    )
    def set_user_password(self, request):
        """Изменение пароля пользователя после сброса."""

        serializer = SetUserPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data.get("email")
        code = serializer.validated_data.get("code")
        password = serializer.validated_data.get("password")

        user = get_object_or_404(User, email=email)

        if user.password_reset_attempts >= MAX_RESET_ATTEMPTS:
            raise ValidationError(
                {"error": "Превышено количество попыток сброса пароля."},
            )

        if not user.password_reset_code or user.password_reset_code != code:
            attempts = MAX_RESET_ATTEMPTS - user.password_reset_attempts
            attempts_word = get_attempts_word(attempts)
            user.password_reset_attempts += 1
            user.save()

            raise ValidationError(
                {
                    "error": "Неверный код для сброса пароля. Осталось "
                    f"{attempts} {attempts_word}."
                },
            )
        with atomic():
            user.password_reset_attempts = 0
            user.password_reset_code = None
            user.set_password(password)
            user.save()

        return Response(
            {"success": "Пароль успешно изменен."},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        url_path="set-user-coordinates",
        permission_classes=[IsAuthenticatedOrReadOnly],
        methods=["post"],
    )
    def set_user_coordinates(self, request, id=None):
        """Метод для обновления координат пользователя."""

        user = self.get_object()
        coordinate_data = request.data

        if self.request.user != user:
            return Response(
                {
                    "error": "Вы не имеете права обновлять "
                    "координаты другого пользователя."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            with atomic():
                if not coordinate_data:
                    return Response(
                        {
                            "message": "Не предоставлены координаты.",
                            "example": {
                                "latitude": 90,
                                "longitude": 180,
                            },
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                user.coordinates, _ = UserCoordinates.objects.get_or_create(
                    id=user.id
                )

                serializer = self.get_serializer(
                    user.coordinates,
                    data=coordinate_data,
                )

                if serializer.is_valid(raise_exception=True):
                    user.coordinates = serializer.save()

                    return Response(
                        {"success": "Координаты обновлены"},
                        status=status.HTTP_200_OK,
                    )
        except ValidationError as e:
            return Response(
                {"error": "Ошибка валидации", "details": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": "Произошла ошибка", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema(tags=["api"])
@extend_schema_view(
    post=extend_schema(
        summary="Создание токена пользователя",
        description="Токен пользователя можно получить только после создания.",
        responses={
            200: UserTokenSerializer,
        },
    )
)
class CustomTokenCreateView(TokenCreateView):
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


@extend_schema(tags=["api"])
@extend_schema_view(
    post=extend_schema(
        summary="Удаление токена пользователя",
        description="Токен пользователя можно удалять после его создания.",
    )
)
class CustomTokenDestroyView(TokenDestroyView):
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
