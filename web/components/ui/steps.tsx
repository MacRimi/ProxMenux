import React from "react"

interface StepProps {
  title: string
  children: React.ReactNode
}

const Step: React.FC<StepProps> = ({ title, children }) => (
  <div className="mb-8">
    <h3 className="text-xl font-semibold mb-2 text-gray-900">{title}</h3>
    {children}
  </div>
)

interface StepsProps {
  children: React.ReactNode
}

const Steps: React.FC<StepsProps> & { Step: typeof Step } = ({ children }) => (
  <div className="space-y-4">
    {React.Children.map(children, (child, index) => (
      <div className="flex items-start">
        <div className="flex-shrink-0 w-8 h-8 bg-blue-500 text-white rounded-full flex items-center justify-center mr-4 mt-1">
          {index + 1}
        </div>
        <div className="flex-grow">{child}</div>
      </div>
    ))}
  </div>
)

Steps.Step = Step

export { Steps }
