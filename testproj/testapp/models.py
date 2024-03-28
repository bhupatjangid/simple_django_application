from django.db import models

class School(models.Model):
    name=models.CharField(max_length=100,default="cse")

class Class(models.Model):
    name=models.CharField(max_length=100,default="cse")
    s_name = models.ForeignKey(School, on_delete=models.CASCADE, related_name="Sch_class")


class Student(models.Model):
    class_name=models.ForeignKey(Class, on_delete=models.CASCADE, related_name="Cls_student")
    name=models.CharField(max_length=100,default='test')
    roll=models.IntegerField(default=1)

class Liberary(models.Model):
    name = models.CharField(max_length=100,default='lib')
    students = models.ManyToManyField(Student, related_name="students_names", blank=True)
