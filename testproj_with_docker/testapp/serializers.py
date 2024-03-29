from rest_framework import serializers

from testapp.models import School, Liberary, Class, Student


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = '__all__'
        

class ClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = Class
        fields = '__all__'

class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = '__all__'

class LiberarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Liberary
        fields = '__all__'