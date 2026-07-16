import aws_cdk as cdk

from s3_line_processor.stack import S3LineProcessorStack

app = cdk.App()
S3LineProcessorStack(app, "S3LineProcessorStack")
app.synth()
