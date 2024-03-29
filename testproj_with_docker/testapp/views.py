from rest_framework import status, viewsets
from django.apps import apps
from collections import defaultdict

from testapp.models import Student, Class, School, Liberary
from testapp.serializers import StudentSerializer, ClassSerializer, SchoolSerializer, LiberarySerializer


class CreateAndViewStudent(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

class CreateAndViewClass(viewsets.ModelViewSet):
    queryset = Class.objects.all()
    serializer_class = ClassSerializer

class CreateAndViewSchool(viewsets.ModelViewSet):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer

class CreateAndViewLiberary(viewsets.ModelViewSet):
    queryset = Liberary.objects.all()
    serializer_class = LiberarySerializer
