# IAM policy for ssmx

A starting-point policy covering every `ssmx` command. Tighten the `Resource`
entries (instance ARNs, tag conditions, parameter paths) for production use.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Discovery",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ssm:DescribeInstanceInformation",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "elasticache:DescribeReplicationGroups",
        "elasticache:DescribeCacheClusters"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Sessions",
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": [
        "arn:aws:ec2:*:*:instance/*",
        "arn:aws:ssm:*::document/AWS-StartPortForwardingSessionToRemoteHost",
        "arn:aws:ssm:*:*:document/SSM-SessionManagerRunShell"
      ]
    },
    {
      "Sid": "EndOwnSessions",
      "Effect": "Allow",
      "Action": ["ssm:TerminateSession", "ssm:ResumeSession"],
      "Resource": "arn:aws:ssm:*:*:session/${aws:userid}-*"
    },
    {
      "Sid": "RunCommand",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:*:*:instance/*",
        "arn:aws:ssm:*::document/AWS-RunShellScript"
      ]
    },
    {
      "Sid": "RunCommandOutput",
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    },
    {
      "Sid": "ParameterStore",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:PutParameter",
        "ssm:DeleteParameter",
        "ssm:DescribeParameters"
      ],
      "Resource": "*"
    }
  ]
}
```

## Restricting by tag

Only allow sessions to instances tagged `ssmx-access=true`:

```json
{
  "Effect": "Allow",
  "Action": "ssm:StartSession",
  "Resource": "arn:aws:ec2:*:*:instance/*",
  "Condition": {
    "StringEquals": { "ssm:resourceTag/ssmx-access": "true" }
  }
}
```

## Restricting Parameter Store to a path

```json
{
  "Effect": "Allow",
  "Action": ["ssm:GetParameter", "ssm:PutParameter"],
  "Resource": "arn:aws:ssm:*:*:parameter/myapp/*"
}
```

`ssm:DescribeParameters` does not support resource-level restrictions and needs `"Resource": "*"`.
